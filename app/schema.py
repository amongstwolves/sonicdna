"""Recipe schema v1.0: parameter bounds, the planner's output schema, and validation.

The wire schema sticks to what Meta documents for strict structured output:
additionalProperties false, every property required, anyOf only below the root.
Numeric bounds are enforced here rather than in the wire schema because Meta's
docs don't say whether minimum/maximum are honoured.
"""

from __future__ import annotations

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


def bounds_errors(recipe: dict[str, Any]) -> list[str]:
    """Out-of-range values in a planner recipe. Switched-off nodes are skipped."""
    errors = []
    for path, (low, high) in BOUNDS.items():
        node_name, field = path.split(".")
        node = recipe.get(node_name)
        if node is None:
            continue
        value = node[field]
        if not low <= value <= high:
            errors.append(f"{path}={value} is outside [{low}, {high}]")
    return errors


def validate_planner_output(output: Any) -> list[str]:
    """Every reason to reject a planner response. An empty list means it is valid."""
    validator = jsonschema.Draft202012Validator(PLANNER_OUTPUT_SCHEMA)
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in validator.iter_errors(output)
    ]
    if errors:
        return errors
    return bounds_errors(output["proposed_recipe_or_delta"])
