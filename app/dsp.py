"""Deterministic offline renderer: the only DSP engine in SonicDNA.

Signal chain: oscillators -> low-pass filter -> ADSR -> distortion -> delay -> loudness.
The same recipe always gives the same samples; there is no randomness anywhere.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal

from app.schema import SAMPLE_RATE, validate_recipe

TARGET_RMS = 0.1  # -20 dBFS
_MAX_DRIVE_GAIN = 10.0
_DELAY_TAIL_FLOOR = 1e-4


def _polyblep(phase: np.ndarray, step: float) -> np.ndarray:
    """Correction that removes most of the aliasing at a waveform's jump."""
    out = np.zeros_like(phase)
    rising = phase < step
    t = phase[rising] / step
    out[rising] = t + t - t * t - 1.0
    falling = phase > 1.0 - step
    t = (phase[falling] - 1.0) / step
    out[falling] = t * t + t + t + 1.0
    return out


def oscillator(kind: str, frequency_hz: float, n_samples: int) -> np.ndarray:
    step = frequency_hz / SAMPLE_RATE
    phase = (np.arange(n_samples) * step) % 1.0
    if kind == "sine":
        return np.sin(2 * np.pi * phase)
    if kind == "saw":
        return 2.0 * phase - 1.0 - _polyblep(phase, step)
    if kind == "square":
        square = np.where(phase < 0.5, 1.0, -1.0)
        return square + _polyblep(phase, step) - _polyblep((phase + 0.5) % 1.0, step)
    raise ValueError(f"unknown oscillator type: {kind}")


def adsr(envelope: dict[str, float], n_samples: int) -> np.ndarray:
    """ADSR over the whole sound. Stages that don't fit are scaled down in proportion."""
    duration = n_samples / SAMPLE_RATE
    attack, decay, release = envelope["attack_s"], envelope["decay_s"], envelope["release_s"]
    total = attack + decay + release
    if total > duration:
        attack, decay, release = (x * duration / total for x in (attack, decay, release))
    sustain = envelope["sustain"]
    times = [0.0, attack, attack + decay, duration - release, duration]
    levels = [0.0, 1.0, sustain, sustain, 0.0]
    return np.interp(np.arange(n_samples) / SAMPLE_RATE, times, levels)


def lowpass(audio: np.ndarray, cutoff_hz: float) -> np.ndarray:
    cutoff = min(cutoff_hz, 0.49 * SAMPLE_RATE)
    return signal.sosfilt(signal.butter(2, cutoff, "lowpass", fs=SAMPLE_RATE, output="sos"), audio)


def distort(audio: np.ndarray, drive: float) -> np.ndarray:
    """tanh waveshaper. Drive 0 leaves the signal unchanged."""
    if drive <= 0:
        return audio
    gain = 1.0 + drive * (_MAX_DRIVE_GAIN - 1.0)
    return np.tanh(gain * audio) / np.tanh(gain)


def delay(audio: np.ndarray, time_ms: float, feedback: float, wet: float) -> np.ndarray:
    """Feedback delay. The tail is cut at the end of the buffer."""
    offset = max(1, round(time_ms * SAMPLE_RATE / 1000))
    out = audio.copy()
    tap_level = wet
    tap_offset = offset
    while tap_offset < len(audio) and tap_level > _DELAY_TAIL_FLOOR:
        out[tap_offset:] += tap_level * audio[: len(audio) - tap_offset]
        tap_level *= feedback
        tap_offset += offset
    return out


def normalize_loudness(audio: np.ndarray) -> np.ndarray:
    """Scale to TARGET_RMS, backing off only if that would clip. Silence stays silent."""
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
    if rms < 1e-10:
        return np.zeros_like(audio)
    scaled = audio * (TARGET_RMS / rms)
    peak = float(np.max(np.abs(scaled)))
    return scaled / peak if peak > 1.0 else scaled


def render(recipe: dict[str, Any]) -> np.ndarray:
    """Render a recipe to loudness-normalised mono samples. Raises ValueError if invalid."""
    errors = validate_recipe(recipe)
    if errors:
        raise ValueError("invalid recipe: " + "; ".join(errors))

    n_samples = round(recipe["duration_s"] * SAMPLE_RATE)
    main = recipe["oscillator"]
    audio = main["gain"] * oscillator(main["type"], main["frequency_hz"], n_samples)
    second = recipe["oscillator_2"]
    if second is not None:
        frequency = min(main["frequency_hz"] * second["frequency_ratio"], 0.45 * SAMPLE_RATE)
        audio = audio + second["gain"] * oscillator(second["type"], frequency, n_samples)

    if recipe["filter"] is not None:
        audio = lowpass(audio, recipe["filter"]["cutoff_hz"])
    audio = audio * adsr(recipe["envelope"], n_samples)
    if recipe["distortion"] is not None:
        audio = distort(audio, recipe["distortion"]["drive"])
    if recipe["delay"] is not None:
        audio = delay(audio, **recipe["delay"])
    return normalize_loudness(audio)
