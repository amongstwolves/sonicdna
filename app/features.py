"""Feature extraction, reference preprocessing and spectrogram PNG."""

from __future__ import annotations

import io
from dataclasses import dataclass

import librosa
import numpy as np
from PIL import Image

from app.dsp import normalize_loudness
from app.schema import SAMPLE_RATE

N_FFT = 2048
HOP = 512
DB_FLOOR = -80.0
_TRIM_THRESHOLD_DB = -60.0
_F0_MIN_HZ = 65.0
_F0_MAX_HZ = 2000.0


@dataclass(frozen=True)
class Features:
    log_mag_db: np.ndarray  # (bins, frames), dB relative to full scale, floored at DB_FLOOR
    centroid_hz: np.ndarray  # (frames,)
    envelope_db: np.ndarray  # (frames,), floored at DB_FLOOR
    flatness: float
    onset_s: float
    f0_hz: float | None  # None when not estimated, or when no pitch was found
    duration_s: float

    def descriptors(self) -> dict[str, float | None]:
        """Summary for the planner, including how the level changes over time."""
        env = self.envelope_db
        peak_frame = int(np.argmax(env))
        third = max(1, len(env) // 3)
        return {
            "duration_s": round(self.duration_s, 3),
            "f0_hz": None if self.f0_hz is None else round(self.f0_hz, 2),
            "spectral_centroid_hz": round(float(np.mean(self.centroid_hz)), 1),
            "spectral_flatness": round(self.flatness, 5),
            "onset_s": round(self.onset_s, 3),
            "time_to_peak_s": round(peak_frame * HOP / SAMPLE_RATE, 3),
            "level_first_third_db": round(float(np.mean(env[:third])), 1),
            "level_middle_third_db": round(float(np.mean(env[third:2 * third])), 1),
            "level_last_third_db": round(float(np.mean(env[2 * third:])), 1),
        }


def preprocess(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Mono at 44.1 kHz, leading silence removed, loudness-normalised.

    Renders start at sample 0, so trimming is what aligns a reference with them.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 2:
        # soundfile returns (samples, channels).
        audio = audio.mean(axis=1)
    if sample_rate != SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=SAMPLE_RATE)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0:
        threshold = peak * 10 ** (_TRIM_THRESHOLD_DB / 20)
        audio = audio[int(np.argmax(np.abs(audio) >= threshold)) :]
    return normalize_loudness(audio)


def estimate_f0(audio: np.ndarray) -> float | None:
    """Median pitch of voiced frames, or None if there are none. Slow, so not per-render."""
    f0, voiced, _ = librosa.pyin(
        audio.astype(np.float32),
        fmin=_F0_MIN_HZ,
        fmax=_F0_MAX_HZ,
        sr=SAMPLE_RATE,
        frame_length=4096,
        hop_length=HOP,
    )
    pitched = f0[voiced & np.isfinite(f0)]
    return float(np.median(pitched)) if len(pitched) else None


def extract(audio: np.ndarray, estimate_pitch: bool = False) -> Features:
    magnitude = np.abs(librosa.stft(audio, n_fft=N_FFT, hop_length=HOP))
    # Absolute dB, so a quieter frame counts as different after loudness normalisation.
    scale = N_FFT / 4
    log_mag = 20 * np.log10(np.maximum(magnitude / scale, 10 ** (DB_FLOOR / 20)))
    power = magnitude**2
    frequencies = librosa.fft_frequencies(sr=SAMPLE_RATE, n_fft=N_FFT)
    centroid = (frequencies[:, None] * magnitude).sum(axis=0) / np.maximum(
        magnitude.sum(axis=0), 1e-10
    )
    rms = librosa.feature.rms(y=audio, frame_length=N_FFT, hop_length=HOP)[0]
    envelope = 20 * np.log10(np.maximum(rms, 10 ** (DB_FLOOR / 20)))
    active = power.sum(axis=0) > 1e-12
    flatness = librosa.feature.spectral_flatness(S=magnitude)[0]
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    onset = int(np.argmax(np.abs(audio) >= 0.1 * peak)) if peak > 0 else 0
    return Features(
        log_mag_db=log_mag,
        centroid_hz=centroid,
        envelope_db=envelope,
        flatness=float(np.mean(flatness[active])) if active.any() else 1.0,
        onset_s=onset / SAMPLE_RATE,
        f0_hz=estimate_f0(audio) if estimate_pitch else None,
        duration_s=len(audio) / SAMPLE_RATE,
    )


def spectrogram_png(audio: np.ndarray) -> bytes:
    """Log-magnitude spectrogram as a grayscale PNG, low frequencies at the bottom."""
    db = librosa.amplitude_to_db(np.abs(librosa.stft(audio, n_fft=N_FFT)), ref=np.max)
    pixels = ((db + 80).clip(0, 80) / 80 * 255).astype(np.uint8)[::-1]
    buffer = io.BytesIO()
    Image.fromarray(pixels).resize((512, 512)).save(buffer, format="PNG")
    return buffer.getvalue()
