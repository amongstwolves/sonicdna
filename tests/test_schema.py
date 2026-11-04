"""Planner output schema and parameter bounds."""

import copy

import pytest

from app.schema import BOUNDS, PLANNER_OUTPUT_SCHEMA, validate_planner_output


@pytest.fixture
def valid_output():
    return {
        "hypothesis": "A filtered saw with a fast decay.",
        "action": "propose_structure",
        "proposed_recipe_or_delta": {
            "oscillator": {"type": "saw", "gain": 0.7},
            "oscillator_2": None,
            "envelope": {"attack_s": 0.01, "decay_s": 0.5, "sustain": 0.2, "release_s": 0.3},
            "filter": {"type": "lowpass", "cutoff_hz": 2800},
            "distortion": None,
            "delay": None,
        },
        "expected_effect": "Matches the centroid and decay.",
        "rationale": "Harmonics fall off above about 3 kHz.",
    }


def test_valid_output_has_no_errors(valid_output):
    assert validate_planner_output(valid_output) == []


def test_all_nodes_switched_on_is_valid(valid_output):
    recipe = valid_output["proposed_recipe_or_delta"]
    recipe["oscillator_2"] = {"type": "sine", "gain": 0.3, "frequency_ratio": 2.0}
    recipe["distortion"] = {"drive": 0.4}
    recipe["delay"] = {"time_ms": 180, "feedback": 0.2, "wet": 0.15}
    assert validate_planner_output(valid_output) == []


@pytest.mark.parametrize("path", sorted(BOUNDS))
@pytest.mark.parametrize("side", ["below", "above"])
def test_every_bound_is_enforced(valid_output, path, side):
    low, high = BOUNDS[path]
    node_name, field = path.split(".")
    recipe = valid_output["proposed_recipe_or_delta"]
    recipe["oscillator_2"] = {"type": "sine", "gain": 0.3, "frequency_ratio": 2.0}
    recipe["distortion"] = {"drive": 0.4}
    recipe["delay"] = {"time_ms": 180, "feedback": 0.2, "wet": 0.15}
    recipe[node_name][field] = low - 1 if side == "below" else high + 1
    errors = validate_planner_output(valid_output)
    assert len(errors) == 1 and path in errors[0]


@pytest.mark.parametrize("path", sorted(BOUNDS))
def test_bounds_are_inclusive(valid_output, path):
    node_name, field = path.split(".")
    recipe = valid_output["proposed_recipe_or_delta"]
    recipe["oscillator_2"] = {"type": "sine", "gain": 0.3, "frequency_ratio": 2.0}
    recipe["distortion"] = {"drive": 0.4}
    recipe["delay"] = {"time_ms": 180, "feedback": 0.2, "wet": 0.15}
    for value in BOUNDS[path]:
        recipe[node_name][field] = value
        assert validate_planner_output(valid_output) == []


def test_unknown_node_rejected(valid_output):
    valid_output["proposed_recipe_or_delta"]["reverb"] = {"wet": 0.5}
    assert validate_planner_output(valid_output)


def test_model_cannot_set_pitch(valid_output):
    valid_output["proposed_recipe_or_delta"]["oscillator"]["frequency_hz"] = 440
    assert validate_planner_output(valid_output)


def test_unknown_oscillator_type_rejected(valid_output):
    valid_output["proposed_recipe_or_delta"]["oscillator"]["type"] = "fm"
    assert validate_planner_output(valid_output)


def test_unknown_action_rejected(valid_output):
    valid_output["action"] = "give_up"
    assert validate_planner_output(valid_output)


@pytest.mark.parametrize(
    "field", ["hypothesis", "action", "proposed_recipe_or_delta", "expected_effect", "rationale"]
)
def test_missing_field_rejected(valid_output, field):
    del valid_output[field]
    assert validate_planner_output(valid_output)


def test_non_object_rejected():
    assert validate_planner_output([])


def _walk_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_objects(value)


def test_wire_schema_meets_metas_strict_rules():
    schema = copy.deepcopy(PLANNER_OUTPUT_SCHEMA)
    assert schema["type"] == "object" and "anyOf" not in schema
    objects = list(_walk_objects(schema))
    assert objects
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    text = repr(schema)
    assert "allOf" not in text and "oneOf" not in text
