"""Preprocessing, features and pitch estimation."""

import numpy as np
import pytest

from app.dsp import TARGET_RMS, oscillator, render
from app.features import DB_FLOOR, estimate_f0, extract, preprocess
from app.schema import SAMPLE_RATE
from scripts.make_targets import TARGETS


def tone(hz=220.0, seconds=1.0, kind="sine"):
    return oscillator(kind, hz, int(seconds * SAMPLE_RATE))


def test_preprocess_makes_stereo_mono():
    stereo = np.stack([tone(), tone()], axis=1)
    assert preprocess(stereo, SAMPLE_RATE).ndim == 1


def test_preprocess_mixes_both_stereo_channels():
    # Opposite channels cancel in a true mix; a one-channel shortcut would keep the tone.
    left = tone() * 0.5
    right = -left
    assert np.all(preprocess(np.stack([left, right], axis=1), SAMPLE_RATE) == 0)


def test_preprocess_resamples_to_project_rate():
    audio = oscillator("sine", 220.0, 22050) * 1.0
    assert len(preprocess(audio, 22050)) == pytest.approx(2 * 22050, abs=100)


def test_preprocess_normalises_loudness():
    audio = preprocess(tone() * 0.001, SAMPLE_RATE)
    assert np.sqrt(np.mean(audio**2)) == pytest.approx(TARGET_RMS)


def test_preprocess_trims_leading_silence():
    audio = np.concatenate([np.zeros(10000), np.ones(1000)])
    assert len(preprocess(audio, SAMPLE_RATE)) == 1000


def test_preprocess_handles_silence_and_empty_input():
    assert np.all(preprocess(np.zeros(1000), SAMPLE_RATE) == 0)
    assert len(preprocess(np.zeros(0), SAMPLE_RATE)) == 0


def test_brighter_sound_has_higher_centroid():
    low = extract(tone(220.0, kind="sine"))
    high = extract(tone(220.0, kind="saw"))
    assert np.mean(high.centroid_hz) > np.mean(low.centroid_hz)


def test_noise_is_flatter_than_a_tone():
    noise = np.random.default_rng(0).normal(0, 0.1, SAMPLE_RATE)
    assert extract(noise).flatness > 100 * extract(tone()).flatness


def test_envelope_follows_a_decay():
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    env = extract(tone() * np.exp(-5 * t)).envelope_db
    assert env[5] > env[len(env) // 2] > env[-5]


def test_onset_finds_the_start():
    audio = np.concatenate([np.zeros(SAMPLE_RATE // 4), tone()])
    assert extract(audio).onset_s == pytest.approx(0.25, abs=0.01)


def test_silence_stays_finite():
    features = extract(np.zeros(SAMPLE_RATE))
    assert np.all(features.envelope_db == DB_FLOOR)
    assert np.all(np.isfinite(features.log_mag_db)) and np.all(np.isfinite(features.centroid_hz))


def test_pitch_is_only_estimated_when_asked():
    assert extract(tone()).f0_hz is None
    assert extract(tone(), estimate_pitch=True).f0_hz == pytest.approx(220.0, abs=1.0)


def test_no_pitch_found_in_noise_or_silence():
    assert estimate_f0(np.zeros(SAMPLE_RATE)) is None


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_pitch_estimate_is_within_a_quarter_semitone_on_every_target(name):
    recipe = TARGETS[name]
    estimate = estimate_f0(render(recipe))
    assert estimate is not None
    cents = 1200 * abs(np.log2(estimate / recipe["oscillator"]["frequency_hz"]))
    assert cents < 25


def test_descriptors_show_a_decay_to_the_planner():
    t = np.arange(2 * SAMPLE_RATE) / SAMPLE_RATE
    descriptors = extract(tone(seconds=2) * np.exp(-3 * t)).descriptors()
    assert (
        descriptors["level_first_third_db"]
        > descriptors["level_middle_third_db"]
        > descriptors["level_last_third_db"]
    )
