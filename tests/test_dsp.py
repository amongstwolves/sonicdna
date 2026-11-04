"""Renderer: determinism, each node's effect, and refusal of bad recipes."""

import copy

import numpy as np
import pytest

from app.dsp import TARGET_RMS, adsr, delay, distort, lowpass, normalize_loudness, oscillator, render
from app.schema import SAMPLE_RATE


@pytest.fixture
def recipe():
    return {
        "schema_version": "1.0",
        "sample_rate": SAMPLE_RATE,
        "duration_s": 1.0,
        "oscillator": {"type": "saw", "frequency_hz": 220.0, "gain": 0.7},
        "oscillator_2": None,
        "envelope": {"attack_s": 0.02, "decay_s": 0.25, "sustain": 0.45, "release_s": 0.35},
        "filter": {"type": "lowpass", "cutoff_hz": 2800.0},
        "distortion": {"drive": 0.35},
        "delay": {"time_ms": 180.0, "feedback": 0.2, "wet": 0.15},
    }


def dominant_hz(audio):
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    return np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)[np.argmax(spectrum)]


def centroid_hz(audio):
    spectrum = np.abs(np.fft.rfft(audio))
    return (np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE) * spectrum).sum() / spectrum.sum()


def test_render_is_deterministic(recipe):
    assert np.array_equal(render(recipe), render(copy.deepcopy(recipe)))


def test_render_does_not_change_the_recipe(recipe):
    before = copy.deepcopy(recipe)
    render(recipe)
    assert recipe == before


def test_render_length_loudness_and_range(recipe):
    audio = render(recipe)
    assert len(audio) == SAMPLE_RATE
    assert np.sqrt(np.mean(audio**2)) == pytest.approx(TARGET_RMS)
    assert np.max(np.abs(audio)) <= 1.0
    assert np.all(np.isfinite(audio))


@pytest.mark.parametrize("kind", ["sine", "saw", "square"])
def test_oscillators_have_the_right_pitch(kind):
    assert dominant_hz(oscillator(kind, 440.0, SAMPLE_RATE)) == pytest.approx(440.0, abs=1.0)


def test_waveforms_differ_in_brightness():
    sine, square, saw = (oscillator(k, 220.0, SAMPLE_RATE) for k in ("sine", "square", "saw"))
    assert centroid_hz(sine) < centroid_hz(square)
    assert centroid_hz(sine) < centroid_hz(saw)


def test_square_has_only_odd_harmonics():
    spectrum = np.abs(np.fft.rfft(oscillator("square", 441.0, SAMPLE_RATE)))
    assert spectrum[882] < spectrum[1323] / 100


def test_polyblep_reduces_aliasing():
    n, hz = SAMPLE_RATE, 3001.0
    naive = 2.0 * ((np.arange(n) * hz / SAMPLE_RATE) % 1.0) - 1.0
    def alias_energy(audio):
        spectrum = np.abs(np.fft.rfft(audio)) ** 2
        harmonics = np.arange(hz, SAMPLE_RATE / 2, hz).astype(int)
        keep = np.ones(len(spectrum), bool)
        keep[harmonics] = False
        return spectrum[keep].sum()
    assert alias_energy(oscillator("saw", hz, n)) < alias_energy(naive) / 3


def test_adsr_shape():
    env = adsr({"attack_s": 0.1, "decay_s": 0.1, "sustain": 0.5, "release_s": 0.2}, SAMPLE_RATE)
    assert env[0] == 0
    assert env[int(0.1 * SAMPLE_RATE)] == pytest.approx(1.0, abs=1e-3)
    assert env[int(0.5 * SAMPLE_RATE)] == pytest.approx(0.5)
    assert env[-1] == pytest.approx(0.0, abs=1e-3)


def test_adsr_stages_too_long_for_the_sound_still_work():
    env = adsr({"attack_s": 2.0, "decay_s": 2.0, "sustain": 0.5, "release_s": 3.0}, SAMPLE_RATE)
    assert len(env) == SAMPLE_RATE and np.all(np.isfinite(env))
    assert 0.99 < env.max() <= 1.0


def test_lowpass_darkens_and_handles_cutoff_above_nyquist():
    saw = oscillator("saw", 220.0, SAMPLE_RATE)
    assert centroid_hz(lowpass(saw, 500.0)) < centroid_hz(lowpass(saw, 5000.0)) < centroid_hz(saw)
    assert np.all(np.isfinite(lowpass(saw, 30000.0)))


def test_distortion_adds_harmonics_and_zero_drive_does_nothing():
    sine = oscillator("sine", 220.0, SAMPLE_RATE)
    assert np.array_equal(distort(sine, 0.0), sine)
    assert centroid_hz(distort(sine, 0.8)) > centroid_hz(sine)


def test_delay_repeats_at_the_right_time_and_level():
    click = np.zeros(SAMPLE_RATE)
    click[0] = 1.0
    out = delay(click, 100.0, 0.5, 0.25)
    assert out[0] == 1.0
    assert out[4410] == pytest.approx(0.25)
    assert out[8820] == pytest.approx(0.125)


def test_delay_at_maximum_feedback_terminates():
    assert np.all(np.isfinite(delay(np.ones(1000), 1.0, 0.9, 1.0)))


def test_second_oscillator_changes_the_sound(recipe):
    second = copy.deepcopy(recipe)
    second["oscillator_2"] = {"type": "sine", "gain": 0.5, "frequency_ratio": 2.0}
    assert not np.array_equal(render(recipe), render(second))


def test_silence_stays_silent(recipe):
    recipe["oscillator"]["gain"] = 0.0
    assert np.array_equal(render(recipe), np.zeros(SAMPLE_RATE))


def test_loud_peaks_never_clip():
    spiky = np.zeros(1000)
    spiky[0] = 1.0
    assert np.max(np.abs(normalize_loudness(spiky))) <= 1.0


def test_second_oscillator_plays_at_its_ratio_of_the_main_pitch(recipe):
    recipe.update(filter=None, distortion=None, delay=None)
    recipe["oscillator"] = {"type": "sine", "frequency_hz": 220.0, "gain": 0.1}
    recipe["oscillator_2"] = {"type": "sine", "gain": 1.0, "frequency_ratio": 2.0}
    assert dominant_hz(render(recipe)) == pytest.approx(440.0, abs=2.0)


@pytest.mark.parametrize("node", ["oscillator_2", "filter", "distortion", "delay"])
def test_optional_nodes_can_be_off(recipe, node):
    recipe[node] = None
    assert len(render(recipe)) == SAMPLE_RATE


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["filter"].update(cutoff_hz=99999),
        lambda r: r["oscillator"].update(frequency_hz=1),
        lambda r: r["oscillator"].update(type="fm"),
        lambda r: r.update(reverb={"wet": 1}),
        lambda r: r.update(duration_s=60),
        lambda r: r.update(sample_rate=48000),
        lambda r: r.pop("envelope"),
    ],
)
def test_invalid_recipes_are_refused(recipe, mutate):
    mutate(recipe)
    with pytest.raises(ValueError, match="invalid recipe"):
        render(recipe)
