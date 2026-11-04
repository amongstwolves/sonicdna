"""Experiment loops and logging: random, optimizer-only and hybrid (AI + optimizer).

All three spend the same kind of render budget through one recorder, so every render is
logged the same way, with its provenance. Pitch always comes from the f0 estimate.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.dsp import render
from app.features import Features, extract
from app.loss import compare
from app.optimizer import LOG_SCALED, LocalSearch, TpeSearch
from app.planner import PlannerContext, PlannerResult
from app.schema import BOUNDS, OSCILLATOR_TYPES, MIN_CANDIDATES, to_planner_recipe, to_recipe

_NODE_ON_PROBABILITY = 0.5
REFINE_RENDERS_PER_ROUND = 3
_MIN_RENDERS_FOR_PLANNER_CALL = MIN_CANDIDATES + 2
_RECENT_EXPERIMENTS_FOR_PLANNER = 8
_RANDOM_STARTS_FOR_LOCAL_BASELINE = 5


def _sample(rng: np.random.Generator, path: str) -> float:
    low, high = BOUNDS[path]
    if path in LOG_SCALED:
        return float(math.exp(rng.uniform(math.log(low), math.log(high))))
    return float(rng.uniform(low, high))


def _node(rng: np.random.Generator, name: str, **fixed: Any) -> dict[str, Any]:
    prefix = f"{name}."
    fields = {
        path[len(prefix) :]: _sample(rng, path) for path in BOUNDS if path.startswith(prefix)
    }
    return {**fixed, **fields}


def sample_planner_recipe(rng: np.random.Generator) -> dict[str, Any]:
    """A uniform-ish random draw from the whole parameter space, inside the bounds."""

    def maybe(name: str, **fixed: Any) -> dict[str, Any] | None:
        return _node(rng, name, **fixed) if rng.random() < _NODE_ON_PROBABILITY else None

    return {
        "oscillator": _node(rng, "oscillator", type=str(rng.choice(OSCILLATOR_TYPES))),
        "oscillator_2": maybe("oscillator_2", type=str(rng.choice(OSCILLATOR_TYPES))),
        "envelope": _node(rng, "envelope"),
        "filter": maybe("filter", type="lowpass"),
        "distortion": maybe("distortion"),
        "delay": maybe("delay"),
    }


def evaluate(recipe: dict[str, Any], target: Features) -> dict[str, Any]:
    """Render and score one recipe. A failed render is reported, not raised."""
    try:
        features = extract(render(recipe))
        comparison = compare(target, features)
    except ValueError as error:
        return {
            "loss": None,
            "components": None,
            "score": None,
            "descriptors": None,
            "failure": str(error),
        }
    return {
        "loss": comparison.loss,
        "components": comparison.components,
        "score": comparison.score,
        "descriptors": features.descriptors(),
        "failure": None,
    }


class _Recorder:
    """Renders, scores and logs one recipe at a time, tracking the best so far."""

    def __init__(
        self, target: Features, mode: str, seed: int, budget: int, log_path: Path | None = None
    ) -> None:
        self.log_path = log_path
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("")
        self.target = target
        self.mode = mode
        self.seed = seed
        self.budget = budget
        self.log: list[dict[str, Any]] = []
        self.best_loss = math.inf
        self.best_entry: dict[str, Any] | None = None

    @property
    def remaining(self) -> int:
        return self.budget - len(self.log)

    def record(self, recipe: dict[str, Any], source: str, **provenance: Any) -> dict[str, Any]:
        result = evaluate(recipe, self.target)
        is_best = result["loss"] is not None and result["loss"] < self.best_loss
        entry = {
            "index": len(self.log),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "seed": self.seed,
            "source": source,
            "planner_call": None,
            "hypothesis": None,
            "rationale": None,
            "expected_effect": None,
            **provenance,
            "recipe": recipe,
            **result,
            "is_best": is_best,
            "best_loss": None,
        }
        if is_best:
            self.best_loss = result["loss"]
            self.best_entry = entry
        entry["best_loss"] = None if math.isinf(self.best_loss) else self.best_loss
        self.log.append(entry)
        if self.log_path is not None:
            # One complete line per render, so a live run can be read while it's going.
            with self.log_path.open("a") as stream:
                stream.write(json.dumps(entry) + "\n")
        return entry


def run_random(
    target: Features,
    frequency_hz: float,
    budget: int,
    seed: int,
    log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Random-search baseline."""
    rng = np.random.default_rng(seed)
    recorder = _Recorder(target, "random", seed, budget, log_path)
    while recorder.remaining > 0:
        recipe = to_recipe(sample_planner_recipe(rng), frequency_hz, target.duration_s)
        recorder.record(recipe, "random")
    return recorder.log


def _refine(
    recorder: _Recorder, renders: int, search: LocalSearch, **provenance: Any
) -> None:
    for _ in range(min(renders, recorder.remaining)):
        recipe = search.propose()
        entry = recorder.record(recipe, "optimizer", **provenance)
        search.report(recipe, entry["loss"])


def run_optimizer_only(
    target: Features,
    frequency_hz: float,
    budget: int,
    seed: int,
    log_path: Path | None = None,
    method: str = "tpe",
) -> list[dict[str, Any]]:
    """Optimizer with no model. Picks its own structure, so it is a fair baseline.

    "tpe" searches structure and parameters together. "restart_local" takes the best of a
    few random structures, then fine-tunes it.
    """
    recorder = _Recorder(target, "optimizer_only", seed, budget, log_path)
    if method == "tpe":
        tpe = TpeSearch(seed)
        while recorder.remaining > 0:
            recipe = to_recipe(tpe.propose(), frequency_hz, target.duration_s)
            tpe.report(recorder.record(recipe, "optimizer")["loss"])
    elif method == "restart_local":
        rng = np.random.default_rng(seed)
        for _ in range(min(_RANDOM_STARTS_FOR_LOCAL_BASELINE, budget)):
            recipe = to_recipe(sample_planner_recipe(rng), frequency_hz, target.duration_s)
            recorder.record(recipe, "optimizer")
        if recorder.best_entry is not None:
            search = LocalSearch(recorder.best_entry["recipe"], recorder.best_loss, rng)
            _refine(recorder, recorder.remaining, search)
    else:
        raise ValueError(f"unknown optimizer method: {method}")
    return recorder.log


def _planner_context(
    recorder: _Recorder, target: Features, spectrogram_png: bytes | None
) -> PlannerContext:
    recent = [
        {
            "source": entry["source"],
            "recipe": to_planner_recipe(entry["recipe"]),
            "normalized_loss": entry["loss"],
            "loss_components": entry["components"],
        }
        for entry in recorder.log[-_RECENT_EXPERIMENTS_FOR_PLANNER:]
        if entry["loss"] is not None
    ]
    best = recorder.best_entry
    return PlannerContext(
        descriptors=target.descriptors(),
        spectrogram_png=spectrogram_png,
        remaining_budget=recorder.remaining,
        best_recipe=None if best is None else to_planner_recipe(best["recipe"]),
        best_loss=None if best is None else best["loss"],
        best_descriptors=None if best is None else best["descriptors"],
        recent=recent,
    )


def _record_candidates(
    recorder: _Recorder,
    result: PlannerResult,
    planner_call: int,
    frequency_hz: float,
    duration_s: float,
) -> None:
    for candidate in result.candidates[: recorder.remaining]:
        recipe = to_recipe(candidate["proposed_recipe_or_delta"], frequency_hz, duration_s)
        recorder.record(
            recipe,
            result.source,
            planner_call=planner_call,
            hypothesis=candidate["hypothesis"],
            rationale=candidate["rationale"],
            expected_effect=candidate["expected_effect"],
            planner_attempts=result.attempts,
            planner_latency_s=round(result.latency_s, 2),
            planner_error=result.error,
        )


def run_hybrid(
    target: Features,
    frequency_hz: float,
    budget: int,
    seed: int,
    planner: Any,
    spectrogram_png: bytes | None = None,
    log_path: Path | None = None,
    refine_per_round: int = REFINE_RENDERS_PER_ROUND,
) -> list[dict[str, Any]]:
    """AI + optimizer: planner candidates, then fine-tuning, then the next planner call.

    Planning stops after a "stop" action, a fallback, the planner's call cap, or too little
    budget for it to matter. The optimizer then spends whatever budget is left.
    """
    rng = np.random.default_rng(seed)
    recorder = _Recorder(target, "hybrid", seed, budget, log_path)
    planner_call = 0
    planning = True
    search: LocalSearch | None = None

    while recorder.remaining > 0:
        if planning and planner.can_call and recorder.remaining >= _MIN_RENDERS_FOR_PLANNER_CALL:
            planner_call += 1
            result = planner.plan(_planner_context(recorder, target, spectrogram_png))
            _record_candidates(recorder, result, planner_call, frequency_hz, target.duration_s)
            planning = result.source == "model" and result.action != "stop"
            # A better recipe from the planner restarts fine-tuning from there.
            if recorder.best_entry is not None and (
                search is None or recorder.best_loss < search.best_loss
            ):
                search = LocalSearch(recorder.best_entry["recipe"], recorder.best_loss, rng)
            renders = refine_per_round if planning else recorder.remaining
        else:
            planning = False
            renders = recorder.remaining

        if search is None:
            # Nothing rendered successfully. Spend the rest on random draws, not silence.
            recipe = to_recipe(sample_planner_recipe(rng), frequency_hz, target.duration_s)
            entry = recorder.record(recipe, "fallback", planner_call=planner_call or None)
            if entry["loss"] is not None:
                search = LocalSearch(recipe, entry["loss"], rng)
            continue
        _refine(recorder, renders, search, planner_call=planner_call or None)
    return recorder.log
