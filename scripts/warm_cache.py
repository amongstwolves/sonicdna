"""Run every audio code path once, so its compiled code is ready before a visitor needs it.

Called during the Docker build to fill the Numba cache, and again when the public server starts.

    python scripts/warm_cache.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dsp import render  # noqa: E402
from app.features import extract, preprocess, spectrogram_png  # noqa: E402
from app.loss import compare  # noqa: E402
from app.schema import SAMPLE_RATE  # noqa: E402
from scripts.make_targets import TARGETS  # noqa: E402


def warm() -> None:
    recipe = next(iter(TARGETS.values())) if isinstance(TARGETS, dict) else TARGETS[0][1]
    audio = preprocess(render(recipe), SAMPLE_RATE)
    features = extract(audio, estimate_pitch=True)
    compare(features, extract(audio))
    spectrogram_png(audio)


if __name__ == "__main__":
    warm()
