"""Sonic Alchemy v1: move a recipe's brightness toward a goal while keeping its pitch.

Prompts are read by fixed rules, with no model call. Requests outside brightness and
atmosphere are refused rather than guessed at. Every variant is rendered and measured,
so what it reports comes from the audio.
"""

from __future__ import annotations

import copy
import itertools
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.dsp import render
from app.features import Features, estimate_f0, extract
from app.schema import BOUNDS, validate_recipe

PITCH_TOLERANCE_CENTS = 25.0
_BRIGHTER = {"subtle": 1.25, "medium": 1.5, "bold": 2.0}
_DARKER = {"subtle": 0.8, "medium": 0.65, "bold": 0.5}
_CUTOFFS_HZ = np.geomspace(200.0, 16000.0, 14)
_EXTRA_DRIVE = (0.0, 0.25, 0.5)
_ATMOSPHERE_DELAY = {"time_ms": 320.0, "feedback": 0.5, "wet": 0.35}
_ATMOSPHERE_RELEASE_FACTOR = 1.5
_MIN_CHANGE = 0.05  # A variant must move brightness at least this much to count.
_MIN_GAP_BETWEEN_VARIANTS = 0.02
_HARMONIC_LAYER = {"type": "saw", "gain": 0.5, "frequency_ratio": 3.0}

_BRIGHT_WORDS = re.compile(r"\b(bright\w*|airy|airier|sharp\w*|crisp\w*)\b", re.I)
_DARK_WORDS = re.compile(r"\b(dark\w*|warm\w*|mellow\w*|dull\w*)\b", re.I)
_ATMOSPHERE_WORDS = re.compile(r"\b(atmospher\w*|ambien\w*|spacious|dreamy|airy)\b", re.I)
_PITCH_WORDS = re.compile(r"\b(keep|preserv\w*|retain\w*|same)\b[^.,;]*\bpitch\b", re.I)
_UNSUPPORTED_WORDS = re.compile(
    r"\b(metallic\w*|pulse\w*|pulsing|rhythm\w*|tremolo|vibrato|robot\w*|gritty|grittier|"
    r"distort\w*|fuzz\w*|reverb\w*|lower the pitch|higher pitch|octave\w*)\b",
    re.I,
)


class AlchemyError(ValueError):
    """The prompt or recipe can't be used. The message says what to do instead."""


@dataclass(frozen=True)
class Goal:
    direction: str | None  # "brighter", "darker", or None to leave brightness alone
    atmosphere: bool
    preserve_pitch_requested: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "atmosphere": self.atmosphere,
            "preserve_pitch_requested": self.preserve_pitch_requested,
            # Pitch is always kept in v1, whether or not the prompt asks for it.
            "preserve_pitch": True,
        }


def parse_goal(prompt: str) -> Goal:
    unsupported = sorted({m.group(0).lower() for m in _UNSUPPORTED_WORDS.finditer(prompt)})
    if unsupported:
        raise AlchemyError(
            f"Alchemy can't do this yet: {', '.join(unsupported)}. "
            'It can change brightness and atmosphere, for example "brighter and more '
            'atmospheric, keep the pitch".'
        )
    brighter = bool(_BRIGHT_WORDS.search(prompt))
    darker = bool(_DARK_WORDS.search(prompt))
    if brighter and darker:
        raise AlchemyError("That asks for both brighter and darker. Choose one.")
    atmosphere = bool(_ATMOSPHERE_WORDS.search(prompt))
    if not (brighter or darker or atmosphere):
        raise AlchemyError(
            'Say what should change: for example "brighter", "darker", or "more atmospheric".'
        )
    direction = "brighter" if brighter else "darker" if darker else None
    return Goal(direction, atmosphere, bool(_PITCH_WORDS.search(prompt)))


def brightness_hz(features: Features) -> float:
    """Spectral centroid weighted by level, so near-silent frames don't skew it."""
    weights = 10 ** (features.envelope_db / 20)
    return float(np.average(features.centroid_hz, weights=weights))


def _with_atmosphere(recipe: dict[str, Any]) -> dict[str, Any]:
    atmospheric = copy.deepcopy(recipe)
    atmospheric["delay"] = dict(_ATMOSPHERE_DELAY)
    release = recipe["envelope"]["release_s"] * _ATMOSPHERE_RELEASE_FACTOR
    atmospheric["envelope"]["release_s"] = min(release, BOUNDS["envelope.release_s"][1])
    return atmospheric


def _brightness_grid(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """Recipes that differ only in tone: cutoff, drive and, for a sine, harmonic content."""
    kinds = [recipe["oscillator"]["type"]]
    if kinds[0] == "sine":
        kinds.append("saw")
    # An integer ratio adds brightness without adding a new pitch.
    layers = [recipe["oscillator_2"]]
    if recipe["oscillator_2"] is None:
        layers.append(dict(_HARMONIC_LAYER))
    base_drive = 0.0 if recipe["distortion"] is None else recipe["distortion"]["drive"]
    grid = []
    for kind, layer, extra, cutoff in itertools.product(
        kinds, layers, _EXTRA_DRIVE, [*_CUTOFFS_HZ, None]
    ):
        drive = min(base_drive + extra, BOUNDS["distortion.drive"][1])
        candidate = copy.deepcopy(recipe)
        candidate["oscillator"]["type"] = kind
        candidate["oscillator_2"] = copy.deepcopy(layer)
        candidate["distortion"] = None if drive == 0 else {"drive": drive}
        candidate["filter"] = (
            None if cutoff is None else {"type": "lowpass", "cutoff_hz": float(cutoff)}
        )
        grid.append(candidate)
    return grid


def _cents(frequency_hz: float | None, reference_hz: float) -> float | None:
    return None if frequency_hz is None else float(1200 * abs(np.log2(frequency_hz / reference_hz)))


def generate_variants(recipe: dict[str, Any], goal: Goal) -> dict[str, Any]:
    """Three measured variants. A candidate that loses the pitch is never returned."""
    errors = validate_recipe(recipe)
    if errors:
        raise AlchemyError("That recipe isn't valid: " + "; ".join(errors))
    pitch_hz = recipe["oscillator"]["frequency_hz"]
    base = extract(render(recipe))
    base_brightness = brightness_hz(base)
    start = _with_atmosphere(recipe) if goal.atmosphere else recipe

    if goal.direction is None:
        steps = {"subtle": 1.0, "medium": 1.0, "bold": 1.0}
    else:
        steps = _BRIGHTER if goal.direction == "brighter" else _DARKER

    tested = []
    for candidate in _brightness_grid(start):
        tested.append((candidate, brightness_hz(extract(render(candidate)))))

    variants: list[dict[str, Any]] = []
    used: list[dict[str, Any]] = []
    for label, factor in steps.items():
        if goal.direction is None:
            # Atmosphere only: scale the effect, and leave tone as it was.
            amount = {"subtle": 0.6, "medium": 1.0, "bold": 1.4}[label]
            only = _with_atmosphere(recipe)
            only["delay"]["wet"] = min(_ATMOSPHERE_DELAY["wet"] * amount, 1.0)
            only["delay"]["feedback"] = min(
                _ATMOSPHERE_DELAY["feedback"] * amount, BOUNDS["delay.feedback"][1]
            )
            ordered = [(only, brightness_hz(extract(render(only))))]
            target = None
        else:
            target = base_brightness * factor
            ordered = sorted(tested, key=lambda item: abs(np.log2(item[1] / target)))
            # Only real movement counts, and each variant has to go further than the last.
            sign = 1.0 if goal.direction == "brighter" else -1.0
            floor = _MIN_CHANGE
            if variants:
                floor = sign * (variants[-1]["brightness_change"] - 1.0) + _MIN_GAP_BETWEEN_VARIANTS
            ordered = [
                item for item in ordered if sign * (item[1] / base_brightness - 1.0) >= floor
            ]
        for candidate, brightness in ordered:
            if candidate in used:
                continue
            audio = render(candidate)
            estimate = estimate_f0(audio)
            cents = _cents(estimate, pitch_hz)
            if cents is None or cents > PITCH_TOLERANCE_CENTS:
                continue
            used.append(candidate)
            variants.append(
                {
                    "label": label,
                    "recipe": candidate,
                    "target_brightness_hz": target,
                    "brightness_hz": brightness,
                    "brightness_change": brightness / base_brightness,
                    "estimated_pitch_hz": estimate,
                    "pitch_shift_cents": cents,
                    "pitch_preserved": True,
                }
            )
            break
    note = None
    if len(variants) < len(steps):
        note = (
            f"Only {len(variants)} of {len(steps)} variants could change this sound "
            "and keep its pitch."
        )
    return {
        "goal": goal.as_dict(),
        "note": note,
        "base_brightness_hz": base_brightness,
        "base_pitch_hz": pitch_hz,
        "renders_tested": len(tested),
        "pitch_tolerance_cents": PITCH_TOLERANCE_CENTS,
        "variants": variants,
    }
