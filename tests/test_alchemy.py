"""Alchemy: prompt rules, measured brightness change, pitch constraint, refusals."""

import copy

import numpy as np
import pytest

import app.alchemy as alchemy
from app.alchemy import AlchemyError, brightness_hz, generate_variants, parse_goal
from app.dsp import render
from app.features import estimate_f0, extract
from app.schema import validate_recipe
from scripts.make_targets import TARGETS

RECIPE = TARGETS["warm_pad"]
DEMO_PROMPT = "brighter and more atmospheric, keep the pitch"


def test_demo_prompt_is_understood():
    goal = parse_goal(DEMO_PROMPT)
    assert goal.direction == "brighter" and goal.atmosphere and goal.preserve_pitch_requested


@pytest.mark.parametrize(
    "prompt, direction, atmosphere",
    [("Darker please", "darker", False), ("make it warmer", "darker", False), ("more ambient", None, True), ("BRIGHT", "brighter", False)],
)
def test_prompt_rules(prompt, direction, atmosphere):
    goal = parse_goal(prompt)
    assert (goal.direction, goal.atmosphere) == (direction, atmosphere)


def test_pitch_is_kept_even_when_not_requested():
    assert parse_goal("brighter").as_dict()["preserve_pitch"] is True
    assert parse_goal("brighter").preserve_pitch_requested is False


@pytest.mark.parametrize(
    "prompt", ["more metallic, preserve the rhythmic pulse", "add tremolo", "brighter and more metallic", "add reverb"]
)
def test_unsupported_requests_are_refused_by_name(prompt):
    with pytest.raises(AlchemyError, match="can't do this yet"):
        parse_goal(prompt)


@pytest.mark.parametrize("prompt", ["", "   ", "make it better"])
def test_vague_prompts_ask_for_a_change(prompt):
    with pytest.raises(AlchemyError, match="Say what should change"):
        parse_goal(prompt)


def test_contradiction_is_refused():
    with pytest.raises(AlchemyError, match="Choose one"):
        parse_goal("brighter and darker")


def test_brightness_ignores_silent_frames():
    audio = render(RECIPE)
    padded = np.concatenate([audio, np.random.default_rng(0).normal(0, 1e-5, 44100)])
    assert brightness_hz(extract(padded)) == pytest.approx(brightness_hz(extract(audio)), rel=0.05)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_brighter_variants_really_move_further_each_step_on_every_target(name):
    result = generate_variants(TARGETS[name], parse_goal("brighter"))
    variants = result["variants"]
    assert variants, "at least one variant should be possible"
    assert (len(variants) == 3) == (result["note"] is None)
    for variant in variants:
        assert validate_recipe(variant["recipe"]) == []
        measured = brightness_hz(extract(render(variant["recipe"])))
        assert variant["brightness_hz"] == pytest.approx(measured)
        assert variant["brightness_change"] >= 1.05
    changes = [v["brightness_change"] for v in variants]
    assert changes == sorted(changes) and len(set(changes)) == len(changes)


def test_no_room_to_move_is_reported_not_faked(monkeypatch):
    monkeypatch.setattr(alchemy, "brightness_hz", lambda features: 1000.0)
    result = generate_variants(RECIPE, parse_goal("brighter"))
    assert result["variants"] == [] and "0 of 3" in result["note"]


def test_targets_are_met_when_the_recipe_has_room():
    for variant in generate_variants(RECIPE, parse_goal("brighter"))["variants"]:
        ratio = variant["brightness_hz"] / variant["target_brightness_hz"]
        assert 0.85 < ratio < 1.15


def test_darker_goes_the_other_way():
    variants = generate_variants(RECIPE, parse_goal("darker"))["variants"]
    assert len(variants) == 3
    changes = [v["brightness_change"] for v in variants]
    assert all(change <= 0.95 for change in changes) and changes == sorted(changes, reverse=True)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_pitch_constraint_holds_when_remeasured(name):
    recipe = TARGETS[name]
    for variant in generate_variants(recipe, parse_goal(DEMO_PROMPT))["variants"]:
        estimate = estimate_f0(render(variant["recipe"]))
        cents = 1200 * abs(np.log2(estimate / recipe["oscillator"]["frequency_hz"]))
        assert cents <= alchemy.PITCH_TOLERANCE_CENTS
        assert variant["recipe"]["oscillator"]["frequency_hz"] == recipe["oscillator"]["frequency_hz"]
        assert variant["pitch_preserved"] is True


def test_candidates_that_lose_the_pitch_are_never_returned(monkeypatch):
    monkeypatch.setattr(alchemy, "estimate_f0", lambda audio: 999.0)
    assert generate_variants(RECIPE, parse_goal("brighter"))["variants"] == []


def test_no_pitch_found_counts_as_lost(monkeypatch):
    monkeypatch.setattr(alchemy, "estimate_f0", lambda audio: None)
    assert generate_variants(RECIPE, parse_goal("brighter"))["variants"] == []


def test_variants_sound_different_from_each_other_and_the_original():
    variants = generate_variants(RECIPE, parse_goal(DEMO_PROMPT))["variants"]
    audios = [render(RECIPE)] + [render(v["recipe"]) for v in variants]
    for i in range(len(audios)):
        for j in range(i + 1, len(audios)):
            assert not np.allclose(audios[i], audios[j])


def test_atmosphere_adds_delay_and_longer_release():
    for variant in generate_variants(RECIPE, parse_goal(DEMO_PROMPT))["variants"]:
        assert variant["recipe"]["delay"] is not None
        assert variant["recipe"]["envelope"]["release_s"] > RECIPE["envelope"]["release_s"]


def test_atmosphere_only_scales_the_effect_and_leaves_tone_alone():
    variants = generate_variants(RECIPE, parse_goal("more atmospheric"))["variants"]
    assert [v["recipe"]["delay"]["wet"] for v in variants] == sorted(v["recipe"]["delay"]["wet"] for v in variants)
    assert all(v["recipe"]["filter"] == RECIPE["filter"] for v in variants)
    assert all(v["target_brightness_hz"] is None for v in variants)


def test_generation_is_deterministic_and_does_not_change_the_input():
    before = copy.deepcopy(RECIPE)
    first = generate_variants(RECIPE, parse_goal(DEMO_PROMPT))
    assert first == generate_variants(RECIPE, parse_goal(DEMO_PROMPT))
    assert RECIPE == before


def test_invalid_recipe_is_refused():
    bad = copy.deepcopy(RECIPE)
    bad["filter"]["cutoff_hz"] = 1e9
    with pytest.raises(AlchemyError, match="isn't valid"):
        generate_variants(bad, parse_goal("brighter"))
