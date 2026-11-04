"""Experiment loop and logging. The random-search baseline lives here for now."""

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
from app.schema import BOUNDS, OSCILLATOR_TYPES, to_recipe

# Sampled on a log scale, because equal ratios matter more than equal differences here.
_LOG_SCALED = {
    "oscillator_2.frequency_ratio",
    "envelope.attack_s",
    "envelope.decay_s",
    "envelope.release_s",
    "filter.cutoff_hz",
    "delay.time_ms",
}
_NODE_ON_PROBABILITY = 0.5


def _sample(rng: np.random.Generator, path: str) -> float:
    low, high = BOUNDS[path]
    if path in _LOG_SCALED:
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
        comparison = compare(target, extract(render(recipe)))
    except ValueError as error:
        return {"loss": None, "components": None, "score": None, "failure": str(error)}
    return {
        "loss": comparison.loss,
        "components": comparison.components,
        "score": comparison.score,
        "failure": None,
    }


def run_random(
    target: Features,
    frequency_hz: float,
    budget: int,
    seed: int,
    log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Random-search baseline. Every render is logged, in order, with best-so-far status."""
    rng = np.random.default_rng(seed)
    log: list[dict[str, Any]] = []
    best_loss = math.inf
    for index in range(budget):
        recipe = to_recipe(sample_planner_recipe(rng), frequency_hz, target.duration_s)
        result = evaluate(recipe, target)
        is_best = result["loss"] is not None and result["loss"] < best_loss
        if is_best:
            best_loss = result["loss"]
        log.append(
            {
                "index": index,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "random",
                "seed": seed,
                "source": "random",
                "recipe": recipe,
                **result,
                "is_best": is_best,
                "best_loss": None if math.isinf(best_loss) else best_loss,
            }
        )
    if log_path is not None:
        write_log(log, log_path)
    return log


def write_log(log: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in log))
