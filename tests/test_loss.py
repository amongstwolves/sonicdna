"""Composite loss: zero on a match, and sensitive to what each component measures."""

import copy

import numpy as np
import pytest

from app.dsp import render
from app.features import extract
from app.loss import WEIGHTS, compare, score_from_loss
from scripts.make_targets import TARGETS

BASE = TARGETS["hollow_square"]


def feats(recipe):
    return extract(render(recipe))


def changed(**nodes):
    recipe = copy.deepcopy(BASE)
    for name, fields in nodes.items():
        recipe[name].update(fields)
    return recipe


def test_identical_sounds_have_zero_loss_and_full_score():
    result = compare(feats(BASE), feats(BASE))
    assert result.loss == 0 and result.score == 1
    assert all(value == 0 for value in result.components.values())


def test_loss_is_the_weighted_sum_of_named_components():
    result = compare(feats(BASE), feats(changed(filter={"cutoff_hz": 800})))
    assert set(result.components) == set(WEIGHTS)
    assert result.loss == pytest.approx(sum(WEIGHTS[k] * v for k, v in result.components.items()))


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_loss_grows_as_cutoff_moves_away():
    target = feats(BASE)
    losses = [compare(target, feats(changed(filter={"cutoff_hz": c}))).loss for c in (3000, 2000, 1000, 400)]
    assert losses == sorted(losses) and losses[-1] > losses[1] > 0


def test_wrong_waveform_costs_more_than_small_tweak():
    target = feats(BASE)
    tweak = compare(target, feats(changed(filter={"cutoff_hz": 2900}))).loss
    wrong = compare(target, feats(changed(oscillator={"type": "sine"}))).loss
    assert wrong > 5 * tweak


def test_wrong_pitch_is_penalised():
    target = feats(BASE)
    assert compare(target, feats(changed(oscillator={"frequency_hz": 392.0}))).components["stft"] > 0.02


def test_envelope_component_sees_a_slower_attack():
    target = feats(BASE)
    slow = compare(target, feats(changed(envelope={"attack_s": 1.0})))
    assert slow.components["envelope"] > 0.02


def test_centroid_component_sees_brightness():
    target = feats(BASE)
    dark = compare(target, feats(changed(filter={"cutoff_hz": 300})))
    assert dark.components["centroid"] > 0.3


def test_shorter_candidate_costs_more_than_a_match():
    short = copy.deepcopy(BASE)
    short["duration_s"] = 1.0
    assert compare(feats(BASE), feats(short)).loss > 0.01


def test_longer_candidate_still_compares():
    long = copy.deepcopy(BASE)
    long["duration_s"] = 3.0
    assert np.isfinite(compare(feats(BASE), feats(long)).loss)


def test_silent_candidate_scores_badly_but_finitely():
    silent = changed(oscillator={"gain": 0.0})
    result = compare(feats(BASE), feats(silent))
    assert np.isfinite(result.loss) and result.score < 0.5


def test_score_falls_from_one_as_loss_grows():
    assert score_from_loss(0.0) == 1
    assert 0 < score_from_loss(1.0) < score_from_loss(0.1) < 1


def test_every_target_is_distinguishable_from_every_other():
    features = {name: feats(recipe) for name, recipe in TARGETS.items()}
    for a in TARGETS:
        for b in TARGETS:
            if a != b:
                assert compare(features[a], features[b]).loss > 0.02, (a, b)
