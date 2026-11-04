"""Numeric search. LocalSearch fine-tunes a fixed structure; TpeSearch searches everything.

LocalSearch changes continuous parameters only, so it can't override the planner's
structural choices. TpeSearch also picks structure, which is what makes it a fair
optimizer-only baseline against the planner.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np
import optuna

from app.schema import BOUNDS, OSCILLATOR_TYPES

# Searched on a log scale, because equal ratios matter more than equal differences here.
LOG_SCALED = {
    "oscillator_2.frequency_ratio",
    "envelope.attack_s",
    "envelope.decay_s",
    "envelope.release_s",
    "filter.cutoff_hz",
    "delay.time_ms",
}
_OPTIONAL_NODES = ("oscillator_2", "filter", "distortion", "delay")
_INITIAL_STEP = 0.05
_MIN_STEP = 0.01
_MAX_STEP = 0.5
_SUCCESS_GROWTH = 1.5
_FAILURE_DECAY = 0.85
_MAX_PARAMS_PER_STEP = 3
_TPE_STARTUP_TRIALS = 6

optuna.logging.set_verbosity(optuna.logging.WARNING)


def continuous_paths(recipe: dict[str, Any]) -> list[str]:
    """Tunable parameters of the nodes that are switched on."""
    paths = [path for path in BOUNDS if recipe.get(path.split(".")[0]) is not None]
    # Output is loudness-normalised, so a lone oscillator's gain only matters if it
    # drives distortion or balances against a second oscillator.
    if recipe.get("oscillator_2") is None and recipe.get("distortion") is None:
        paths.remove("oscillator.gain")
    return paths


def _nudge(value: float, path: str, step: float, rng: np.random.Generator) -> float:
    low, high = BOUNDS[path]
    if path in LOG_SCALED:
        span = math.log(high) - math.log(low)
        moved = math.exp(math.log(max(value, low)) + rng.normal(0.0, step * span))
    else:
        moved = value + rng.normal(0.0, step * (high - low))
    return float(min(max(moved, low), high))


class LocalSearch:
    """A (1+1) evolution strategy: move from the best recipe, adapting the step size."""

    def __init__(self, recipe: dict[str, Any], loss: float, rng: np.random.Generator) -> None:
        self.best = copy.deepcopy(recipe)
        self.best_loss = loss
        self.step = _INITIAL_STEP
        self._rng = rng

    def propose(self) -> dict[str, Any]:
        recipe = copy.deepcopy(self.best)
        paths = continuous_paths(recipe)
        count = int(self._rng.integers(1, min(_MAX_PARAMS_PER_STEP, len(paths)) + 1))
        for path in self._rng.choice(paths, size=count, replace=False):
            node, field = str(path).split(".")
            recipe[node][field] = _nudge(recipe[node][field], str(path), self.step, self._rng)
        return recipe

    def report(self, recipe: dict[str, Any], loss: float | None) -> None:
        if loss is not None and loss < self.best_loss:
            self.best = copy.deepcopy(recipe)
            self.best_loss = loss
            self.step = min(self.step * _SUCCESS_GROWTH, _MAX_STEP)
        else:
            self.step = max(self.step * _FAILURE_DECAY, _MIN_STEP)


class TpeSearch:
    """Optuna TPE over structure and parameters, driven one render at a time."""

    def __init__(self, seed: int) -> None:
        sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=_TPE_STARTUP_TRIALS)
        self._study = optuna.create_study(sampler=sampler)
        self._trial: optuna.Trial | None = None

    def _float(self, path: str) -> float:
        low, high = BOUNDS[path]
        return self._trial.suggest_float(path, low, high, log=path in LOG_SCALED)

    def _fields(self, node: str) -> dict[str, float]:
        prefix = f"{node}."
        return {
            path[len(prefix) :]: self._float(path) for path in BOUNDS if path.startswith(prefix)
        }

    def propose(self) -> dict[str, Any]:
        """A planner-form recipe: no pitch, because that comes from the f0 estimate."""
        self._trial = self._study.ask()
        recipe: dict[str, Any] = {
            "oscillator": {
                "type": self._trial.suggest_categorical("oscillator.type", OSCILLATOR_TYPES),
                **self._fields("oscillator"),
            },
            "envelope": self._fields("envelope"),
        }
        for node in _OPTIONAL_NODES:
            if not self._trial.suggest_categorical(f"{node}.on", [True, False]):
                recipe[node] = None
                continue
            fields = self._fields(node)
            if node == "oscillator_2":
                fields["type"] = self._trial.suggest_categorical(
                    "oscillator_2.type", OSCILLATOR_TYPES
                )
            elif node == "filter":
                fields["type"] = "lowpass"
            recipe[node] = fields
        return recipe

    def report(self, loss: float | None) -> None:
        if loss is None:
            self._study.tell(self._trial, state=optuna.trial.TrialState.FAIL)
        else:
            self._study.tell(self._trial, loss)
