"""Planner: request, validation, retry once, fallback, and the hard call cap."""

import json

import httpx
import pytest

from app.planner import MAX_CALLS_PER_RUN, Planner, PlannerContext, build_payload, fallback_candidates
from app.schema import PLANNER_RESPONSE_SCHEMA, validate_planner_response

RECIPE = {
    "oscillator": {"type": "saw", "gain": 0.7},
    "oscillator_2": None,
    "envelope": {"attack_s": 0.01, "decay_s": 0.5, "sustain": 0.2, "release_s": 0.3},
    "filter": {"type": "lowpass", "cutoff_hz": 2800},
    "distortion": None,
    "delay": None,
}


def candidate(**recipe_changes):
    return {
        "hypothesis": "A saw.",
        "proposed_recipe_or_delta": {**RECIPE, **recipe_changes},
        "expected_effect": "Closer.",
        "rationale": "Harmonics.",
    }


def reply(n=3, action="propose_structure", **recipe_changes):
    return {"action": action, "candidates": [candidate(**recipe_changes) for _ in range(n)]}


def http_ok(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 5}})


class Scripted:
    """A fake API that returns a fixed sequence of responses and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(json.loads(request.content))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make(scripted, **kwargs):
    return Planner("k", transport=httpx.MockTransport(scripted), **kwargs)


def context(**kwargs):
    return PlannerContext(
        descriptors={"f0_hz": 220.0, "spectral_centroid_hz": 1400.0}, spectrogram_png=b"png", remaining_budget=20, **kwargs
    )


@pytest.mark.parametrize("n", [3, 4, 5])
def test_three_to_five_candidates_are_valid(n):
    assert validate_planner_response(reply(n)) == []


@pytest.mark.parametrize("n", [0, 1, 2, 6])
def test_other_candidate_counts_are_rejected(n):
    assert validate_planner_response(reply(n))


def test_stop_needs_no_candidates():
    assert validate_planner_response(reply(0, action="stop")) == []


def test_out_of_bounds_candidate_is_named():
    bad = reply(3)
    bad["candidates"][1]["proposed_recipe_or_delta"]["filter"] = {"type": "lowpass", "cutoff_hz": 99999}
    errors = validate_planner_response(bad)
    assert len(errors) == 1 and errors[0].startswith("candidates/1")


def test_unknown_node_is_rejected():
    assert validate_planner_response(reply(3, reverb={"wet": 1}))


def test_model_cannot_set_pitch():
    assert validate_planner_response(reply(3, oscillator={"type": "saw", "gain": 0.5, "frequency_hz": 440}))


def test_wire_schema_follows_metas_strict_rules():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(PLANNER_RESPONSE_SCHEMA)
    assert "allOf" not in repr(PLANNER_RESPONSE_SCHEMA) and "oneOf" not in repr(PLANNER_RESPONSE_SCHEMA)


def test_payload_has_image_in_user_message_and_state_as_json():
    payload = build_payload(context(best_loss=0.2), "m", "low", [])
    assert isinstance(payload["messages"][0]["content"], str)
    text, image = payload["messages"][1]["content"]
    assert image["type"] == "image_url"
    state = json.loads(text["text"].split("\n\n")[0])
    assert state["best_normalized_loss_so_far"] == 0.2
    assert state["remaining_render_budget"] == 20
    assert payload["reasoning_effort"] == "low"


def test_reasoning_effort_is_omitted_by_default():
    assert "reasoning_effort" not in build_payload(context(), "m", None, [])


def test_valid_reply_returns_model_candidates():
    scripted = Scripted(http_ok(json.dumps(reply(4))))
    result = make(scripted).plan(context())
    assert result.source == "model" and len(result.candidates) == 4 and result.attempts == 1
    assert result.error is None and len(scripted.requests) == 1


def test_invalid_reply_retries_once_and_tells_the_model_why():
    scripted = Scripted(http_ok(json.dumps(reply(2))), http_ok(json.dumps(reply(3))))
    result = make(scripted).plan(context())
    assert result.source == "model" and result.attempts == 2
    assert "rejected" in scripted.requests[1]["messages"][1]["content"][0]["text"]


@pytest.mark.parametrize(
    "first",
    [
        http_ok("not json"),
        http_ok(json.dumps(reply(3, reverb={"wet": 1}))),
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"choices": []}),
        httpx.ConnectError("no route"),
        httpx.ReadTimeout("slow"),
    ],
)
def test_two_failures_end_in_the_deterministic_fallback(first):
    scripted = Scripted(first, httpx.Response(500, text="still down"))
    result = make(scripted).plan(context())
    assert result.source == "fallback" and result.attempts == 2 and result.error
    assert len(scripted.requests) == 2
    assert validate_planner_response({"action": "propose_structure", "candidates": result.candidates}) == []


def test_api_key_does_not_reach_the_error_message():
    scripted = Scripted(httpx.Response(401, text="nope"), httpx.Response(401, text="nope"))
    assert "secret-value" not in Planner("secret-value", transport=httpx.MockTransport(scripted)).plan(context()).error


def test_cap_counts_retries_and_is_never_exceeded():
    bad = lambda: httpx.Response(500, text="down")
    scripted = Scripted(*[bad() for _ in range(10)])
    planner = make(scripted)
    for _ in range(5):
        planner.plan(context())
    assert len(scripted.requests) == MAX_CALLS_PER_RUN == planner.calls_made
    assert not planner.can_call


def test_plan_at_the_cap_makes_no_call_and_falls_back():
    scripted = Scripted()
    result = make(scripted, max_calls=0).plan(context())
    assert result.source == "fallback" and result.attempts == 0 and scripted.requests == []


def test_a_retry_can_be_cut_short_by_the_cap():
    scripted = Scripted(httpx.Response(500, text="down"))
    result = make(scripted, max_calls=1).plan(context())
    assert result.source == "fallback" and len(scripted.requests) == 1


def test_fallback_is_deterministic_and_uses_descriptors():
    dark = {"f0_hz": 220.0, "spectral_centroid_hz": 300.0, "time_to_peak_s": 0.5}
    bright = {"f0_hz": 220.0, "spectral_centroid_hz": 3000.0, "time_to_peak_s": 0.01}
    assert fallback_candidates(dark) == fallback_candidates(dark)
    cutoff = lambda d: fallback_candidates(d)[0]["proposed_recipe_or_delta"]["filter"]["cutoff_hz"]
    assert cutoff(dark) < cutoff(bright)


@pytest.mark.parametrize(
    "descriptors",
    [
        {},
        {"f0_hz": None, "spectral_centroid_hz": None},
        {"spectral_centroid_hz": 1e9, "time_to_peak_s": 100.0, "level_first_third_db": 0.0, "level_last_third_db": -80.0},
        {"spectral_centroid_hz": 0.0, "time_to_peak_s": 0.0, "level_first_third_db": -80.0, "level_last_third_db": 0.0},
    ],
)
def test_fallback_is_always_in_bounds(descriptors):
    response = {"action": "propose_structure", "candidates": fallback_candidates(descriptors)}
    assert validate_planner_response(response) == []
