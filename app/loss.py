"""Composite loss between a target and a candidate, with named components.

All components are 0 for identical sounds and grow with difference:
- stft: mean absolute log-magnitude difference, as a fraction of the 80 dB range
- centroid: mean brightness difference in octaves over frames where the target is audible
- envelope: mean absolute level difference over time, as a fraction of the 80 dB range

score = 1 / (1 + 10 * loss) is a normalised metric between 0 and 1, with 1 meaning the
features match exactly. It is not accuracy, and it is not perceptual similarity.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.features import DB_FLOOR, Features

WEIGHTS = {"stft": 0.5, "centroid": 0.2, "envelope": 0.3}
_AUDIBLE_DB = -60.0
_SCORE_SCALE = 10.0


@dataclass(frozen=True)
class Comparison:
    loss: float
    components: dict[str, float]
    score: float


def _fit(values: np.ndarray, n_frames: int, fill: float) -> np.ndarray:
    """Crop or pad the last axis to n_frames, so a length mismatch counts as a difference."""
    if values.shape[-1] >= n_frames:
        return values[..., :n_frames]
    pad = [(0, 0)] * (values.ndim - 1) + [(0, n_frames - values.shape[-1])]
    return np.pad(values, pad, constant_values=fill)


def score_from_loss(loss: float) -> float:
    return 1.0 / (1.0 + _SCORE_SCALE * loss)


def compare(target: Features, candidate: Features) -> Comparison:
    n_frames = target.log_mag_db.shape[-1]
    stft = np.mean(
        np.abs(target.log_mag_db - _fit(candidate.log_mag_db, n_frames, DB_FLOOR))
    ) / abs(DB_FLOOR)

    audible = target.envelope_db > _AUDIBLE_DB
    candidate_centroid = _fit(candidate.centroid_hz, n_frames, 1.0)
    ratio = np.maximum(target.centroid_hz[audible], 1.0) / np.maximum(
        candidate_centroid[audible], 1.0
    )
    centroid = np.mean(np.abs(np.log2(ratio))) if audible.any() else 0.0

    envelope = np.mean(
        np.abs(target.envelope_db - _fit(candidate.envelope_db, n_frames, DB_FLOOR))
    ) / abs(DB_FLOOR)

    components = {"stft": float(stft), "centroid": float(centroid), "envelope": float(envelope)}
    loss = sum(WEIGHTS[name] * value for name, value in components.items())
    return Comparison(loss=loss, components=components, score=score_from_loss(loss))
