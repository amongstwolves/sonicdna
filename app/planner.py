"""Muse planner: structural proposals, validation, retry once, deterministic fallback.

One call returns 3-5 candidate recipes. Every HTTP attempt, retries included, counts
toward the per-run cap, so a run can never spend more than MAX_CALLS_PER_RUN calls.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.schema import (
    BOUNDS,
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    PLANNER_RESPONSE_SCHEMA,
    validate_planner_response,
)

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
MAX_CALLS_PER_RUN = 4
REQUEST_TIMEOUT_S = 180
_MAX_ATTEMPTS_PER_PLAN = 2

_SYSTEM_PROMPT = (
    "You plan experiments that reconstruct a sound with a small synthesizer. You make the "
    "structural decisions: oscillator types, which nodes are on, and rough parameter regions. "
    "A numeric optimizer fine-tunes the continuous values after you, so don't aim for exact "
    "values. Make candidates differ in structure rather than small value changes. Read the "
    "spectrogram image as time on x and frequency on y, low frequencies at the bottom, and use "
    "the level-over-time descriptors to judge the envelope. Stay inside the bounds. "
    'Use action "propose_structure" for new structures, "refine_region" to explore around the '
    'best structure, or "stop" with an empty candidates list if more proposals are unlikely '
    "to help."
)


@dataclass
class PlannerContext:
    descriptors: dict[str, Any]
    spectrogram_png: bytes | None
    remaining_budget: int
    best_recipe: dict[str, Any] | None = None
    best_loss: float | None = None
    best_descriptors: dict[str, Any] | None = None
    recent: list[dict[str, Any]] = field(default_factory=list)
    constraints: str = "Reconstruct the target as closely as possible."


@dataclass
class PlannerResult:
    source: str  # "model" or "fallback"
    action: str
    candidates: list[dict[str, Any]]
    attempts: int
    latency_s: float
    error: str | None = None
    usage: dict[str, Any] | None = None


def build_payload(
    context: PlannerContext, model: str, reasoning_effort: str | None, retry_errors: list[str]
) -> dict[str, Any]:
    state = {
        "target_descriptors": context.descriptors,
        "allowed_nodes": {
            "required": ["oscillator", "envelope"],
            "optional_set_null_to_switch_off": ["oscillator_2", "filter", "distortion", "delay"],
            "oscillator_types": ["sine", "saw", "square"],
        },
        "parameter_bounds_min_max": BOUNDS,
        "best_recipe_so_far": context.best_recipe,
        "best_normalized_loss_so_far": context.best_loss,
        "best_recipe_descriptors": context.best_descriptors,
        "recent_experiments": context.recent,
        "remaining_render_budget": context.remaining_budget,
        "user_constraints": context.constraints,
    }
    text = (
        f"{json.dumps(state)}\n\nPitch is fixed from the f0 estimate, so don't propose it. "
        f"Lower normalized loss is better. Propose {MIN_CANDIDATES}-{MAX_CANDIDATES} candidates."
    )
    if retry_errors:
        text += "\n\nYour previous response was rejected: " + "; ".join(retry_errors[:10])
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if context.spectrogram_png is not None:
        encoded = base64.b64encode(context.spectrogram_png).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
        )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "developer", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "planner_response",
                "strict": True,
                "schema": PLANNER_RESPONSE_SCHEMA,
            },
        },
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def fallback_candidates(descriptors: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic structures derived from the measured descriptors. No model involved."""
    f0 = descriptors.get("f0_hz") or 220.0
    centroid = descriptors.get("spectral_centroid_hz") or 1000.0
    cutoff = min(max(centroid * 3.0, BOUNDS["filter.cutoff_hz"][0]), BOUNDS["filter.cutoff_hz"][1])
    attack = min(
        max(descriptors.get("time_to_peak_s") or 0.01, BOUNDS["envelope.attack_s"][0]),
        BOUNDS["envelope.attack_s"][1],
    )
    first = descriptors.get("level_first_third_db")
    last = descriptors.get("level_last_third_db")
    drop_db = max((first or 0.0) - (last or 0.0), 0.0)
    sustain = min(max(10 ** (-drop_db / 20), 0.0), 1.0)
    envelope = {"attack_s": attack, "decay_s": 0.4, "sustain": sustain, "release_s": 0.3}

    def candidate(kind: str, hypothesis: str, use_filter: bool) -> dict[str, Any]:
        return {
            "hypothesis": hypothesis,
            "proposed_recipe_or_delta": {
                "oscillator": {"type": kind, "gain": 0.7},
                "oscillator_2": None,
                "envelope": dict(envelope),
                "filter": {"type": "lowpass", "cutoff_hz": cutoff} if use_filter else None,
                "distortion": None,
                "delay": None,
            },
            "expected_effect": "A starting structure for the optimizer.",
            "rationale": (
                "Deterministic fallback from measured descriptors; "
                f"brightness is {centroid / f0:.1f}x the pitch."
            ),
        }

    return [
        candidate("saw", "Fallback: a filtered saw, for a tone rich in harmonics.", True),
        candidate("square", "Fallback: a filtered square, for a hollow tone.", True),
        candidate("sine", "Fallback: a plain sine, for a pure tone.", False),
    ]


class Planner:
    """Calls Muse with a per-run cap. Create one per run; it holds no other state."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str | None = None,
        max_calls: int = MAX_CALLS_PER_RUN,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._max_calls = max_calls
        self._transport = transport
        self.calls_made = 0

    @property
    def can_call(self) -> bool:
        return self.calls_made < self._max_calls

    def _attempt(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """One HTTP call. Raises ValueError with every reason the reply can't be used."""
        self.calls_made += 1
        try:
            with httpx.Client(
                base_url=BASE_URL, timeout=REQUEST_TIMEOUT_S, transport=self._transport
            ) as client:
                response = client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as error:
            raise ValueError(f"request error: {type(error).__name__}") from error
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
            parsed = json.loads(body["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ValueError(f"unusable response: {error!r}") from error
        errors = validate_planner_response(parsed)
        if errors:
            raise ValueError("; ".join(errors))
        return parsed, body.get("usage")

    def plan(self, context: PlannerContext) -> PlannerResult:
        """Candidates from the model, retrying once, or else the deterministic fallback."""
        started = time.monotonic()
        attempts = 0
        retry_errors: list[str] = []
        last_error = "planner call cap reached"
        while attempts < _MAX_ATTEMPTS_PER_PLAN and self.can_call:
            attempts += 1
            payload = build_payload(context, self._model, self._reasoning_effort, retry_errors)
            try:
                parsed, usage = self._attempt(payload)
            except ValueError as error:
                last_error = str(error)
                retry_errors = [last_error]
                continue
            return PlannerResult(
                source="model",
                action=parsed["action"],
                candidates=parsed["candidates"][:MAX_CANDIDATES],
                attempts=attempts,
                latency_s=time.monotonic() - started,
                usage=usage,
            )
        return PlannerResult(
            source="fallback",
            action="propose_structure",
            candidates=fallback_candidates(context.descriptors),
            attempts=attempts,
            latency_s=time.monotonic() - started,
            error=last_error,
        )


def planner_from_env(root: Path, reasoning_effort: str | None = None) -> Planner:
    load_dotenv(root / ".env")
    api_key = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not api_key:
        raise SystemExit("No API key. Set META_API_KEY in .env.")
    model = os.environ.get("META_MODEL") or DEFAULT_MODEL
    return Planner(api_key, model=model, reasoning_effort=reasoning_effort)
