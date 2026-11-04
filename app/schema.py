"""Recipe schema v1.0: parameter bounds, the planner's output schema, and validation.

The wire schema sticks to what Meta documents for strict structured output:
additionalProperties false, every property required, anyOf only below the root.
Numeric bounds are enforced here rather than in the wire schema because Meta's
docs don't say whether minimum/maximum are honoured.
"""

from __future__ import annotations

import copy
from typing import Any

import jsonschema

SCHEMA_VERSION = "1.0"
OSCILLATOR_TYPES = ["sine", "saw", "square"]
ACTIONS = ["propose_structure", "refine_region", "stop"]

# path -> (min, max), inclusive. Paths are relative to the planner's recipe.
BOUNDS: dict[str, tuple[float, float]] = {
    "oscillator.gain": (0.0, 1.0),
    "oscillator_2.gain": (0.0, 1.0),
    "oscillator_2.frequency_ratio": (0.25, 4.0),
    "envelope.attack_s": (0.001, 2.0),
    "envelope.decay_s": (0.001, 2.0),
    "envelope.sustain": (0.0, 1.0),
    "envelope.release_s": (0.001, 3.0),
    "filter.cutoff_hz": (20.0, 20000.0),
    "distortion.drive": (0.0, 1.0),
    "delay.time_ms": (1.0, 1000.0),
    "delay.feedback": (0.0, 0.9),
    "delay.wet": (0.0, 1.0),
}


# The renderer's full recipe adds the pitch the planner isn't allowed to set.
RECIPE_BOUNDS = {
    **BOUNDS,
    "oscillator.frequency_hz": (20.0, 5000.0),
    "duration_s": (0.1, 5.0),
}
SAMPLE_RATE = 44100


def _obj(**properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _optional(node: dict[str, Any]) -> dict[str, Any]:
    """A node the planner can switch off by returning null."""
    return {"anyOf": [node, {"type": "null"}]}


_NUM = {"type": "number"}
_OSC_TYPE = {"type": "string", "enum": OSCILLATOR_TYPES}

# Pitch comes from the f0 estimate (locked decision 5), so the planner has no
# frequency_hz field. A second oscillator is expressed as a ratio of that pitch.
PLANNER_RECIPE_SCHEMA = _obj(
    oscillator=_obj(type=_OSC_TYPE, gain=_NUM),
    oscillator_2=_optional(_obj(type=_OSC_TYPE, gain=_NUM, frequency_ratio=_NUM)),
    envelope=_obj(attack_s=_NUM, decay_s=_NUM, sustain=_NUM, release_s=_NUM),
    filter=_optional(_obj(type={"type": "string", "enum": ["lowpass"]}, cutoff_hz=_NUM)),
    distortion=_optional(_obj(drive=_NUM)),
    delay=_optional(_obj(time_ms=_NUM, feedback=_NUM, wet=_NUM)),
)

PLANNER_OUTPUT_SCHEMA = _obj(
    hypothesis={"type": "string"},
    action={"type": "string", "enum": ACTIONS},
    proposed_recipe_or_delta=PLANNER_RECIPE_SCHEMA,
    expected_effect={"type": "string"},
    rationale={"type": "string"},
)


MIN_CANDIDATES = 3
MAX_CANDIDATES = 5

# One planner call proposes several recipes, because each call takes about 28 s.
PLANNER_RESPONSE_SCHEMA = _obj(
    action={"type": "string", "enum": ACTIONS},
    candidates={
        "type": "array",
        "items": _obj(
            hypothesis={"type": "string"},
            proposed_recipe_or_delta=PLANNER_RECIPE_SCHEMA,
            expected_effect={"type": "string"},
            rationale={"type": "string"},
        ),
    },
)

RECIPE_SCHEMA = _obj(
    schema_version={"type": "string", "enum": [SCHEMA_VERSION]},
    sample_rate={"type": "integer", "enum": [SAMPLE_RATE]},
    duration_s=_NUM,
    oscillator=_obj(type=_OSC_TYPE, frequency_hz=_NUM, gain=_NUM),
    oscillator_2=_optional(_obj(type=_OSC_TYPE, gain=_NUM, frequency_ratio=_NUM)),
    envelope=PLANNER_RECIPE_SCHEMA["properties"]["envelope"],
    filter=PLANNER_RECIPE_SCHEMA["properties"]["filter"],
    distortion=PLANNER_RECIPE_SCHEMA["properties"]["distortion"],
    delay=PLANNER_RECIPE_SCHEMA["properties"]["delay"],
)


def bounds_errors(
    recipe: dict[str, Any], bounds: dict[str, tuple[float, float]] = BOUNDS
) -> list[str]:
    """Out-of-range values in a recipe. Switched-off nodes are skipped."""
    errors = []
    for path, (low, high) in bounds.items():
        parts = path.split(".")
        node = recipe if len(parts) == 1 else recipe.get(parts[0])
        if node is None:
            continue
        value = node[parts[-1]]
        if not low <= value <= high:
            errors.append(f"{path}={value} is outside [{low}, {high}]")
    return errors


def _schema_errors(schema: dict[str, Any], value: Any) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in jsonschema.Draft202012Validator(schema).iter_errors(value)
    ]


def validate_recipe(recipe: Any) -> list[str]:
    """Every reason the renderer would refuse a recipe. Empty means it is valid."""
    return _schema_errors(RECIPE_SCHEMA, recipe) or bounds_errors(recipe, RECIPE_BOUNDS)


def to_recipe(planner_recipe: dict[str, Any], f0_hz: float, duration_s: float) -> dict[str, Any]:
    """A renderable recipe from a planner recipe, with pitch from the f0 estimate."""
    recipe = copy.deepcopy(planner_recipe)
    recipe["oscillator"]["frequency_hz"] = f0_hz
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_rate": SAMPLE_RATE,
        "duration_s": duration_s,
        **recipe,
    }


def validate_planner_output(output: Any) -> list[str]:
    """Every reason to reject a planner response. An empty list means it is valid."""
    errors = _schema_errors(PLANNER_OUTPUT_SCHEMA, output)
    if errors:
        return errors
    return bounds_errors(output["proposed_recipe_or_delta"])


def validate_planner_response(response: Any) -> list[str]:
    """Every reason to reject a multi-candidate response. Empty means it is valid."""
    errors = _schema_errors(PLANNER_RESPONSE_SCHEMA, response)
    if errors:
        return errors
    candidates = response["candidates"]
    if response["action"] != "stop" and not MIN_CANDIDATES <= len(candidates) <= MAX_CANDIDATES:
        errors.append(
            f"expected {MIN_CANDIDATES}-{MAX_CANDIDATES} candidates, got {len(candidates)}"
        )
    for index, candidate in enumerate(candidates):
        errors += [
            f"candidates/{index}: {error}"
            for error in bounds_errors(candidate["proposed_recipe_or_delta"])
        ]
    return errors


def to_planner_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """The planner's view of a full recipe: no pitch, sample rate or duration."""
    planner = {key: copy.deepcopy(recipe[key]) for key in PLANNER_RECIPE_SCHEMA["properties"]}
    del planner["oscillator"]["frequency_hz"]
    return planner
