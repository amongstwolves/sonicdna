"""Generate the synthetic reference set: WAVs plus known ground-truth recipes.

The held-out split is fixed here, before any tuning. Don't tune anything against it.

    python scripts/make_targets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import soundfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dsp import render  # noqa: E402
from app.schema import SAMPLE_RATE, SCHEMA_VERSION  # noqa: E402

OUT_DIR = ROOT / "data" / "targets"
DURATION_S = 2.0
HELD_OUT = ("glass_pluck", "fuzz_lead", "echo_stack")


def _recipe(
    kind: str,
    hz: float,
    gain: float,
    adsr: tuple[float, float, float, float],
    cutoff: float | None = None,
    drive: float | None = None,
    delay: tuple[float, float, float] | None = None,
    second: tuple[str, float, float] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_rate": SAMPLE_RATE,
        "duration_s": DURATION_S,
        "oscillator": {"type": kind, "frequency_hz": hz, "gain": gain},
        "oscillator_2": (
            None
            if second is None
            else {"type": second[0], "frequency_ratio": second[1], "gain": second[2]}
        ),
        "envelope": dict(zip(("attack_s", "decay_s", "sustain", "release_s"), adsr)),
        "filter": None if cutoff is None else {"type": "lowpass", "cutoff_hz": cutoff},
        "distortion": None if drive is None else {"drive": drive},
        "delay": (
            None
            if delay is None
            else dict(zip(("time_ms", "feedback", "wet"), delay))
        ),
    }


TARGETS: dict[str, dict[str, Any]] = {
    # Easy: one oscillator, at most a filter.
    "soft_sine": _recipe("sine", 261.63, 0.8, (0.08, 0.3, 0.6, 0.5)),
    "bass_saw": _recipe("saw", 98.0, 0.8, (0.01, 0.2, 0.7, 0.2), cutoff=900),
    "hollow_square": _recipe("square", 196.0, 0.7, (0.02, 0.4, 0.5, 0.3), cutoff=3000),
    "glass_pluck": _recipe("saw", 523.25, 0.6, (0.002, 0.5, 0.0, 0.2), cutoff=6000),
    # Medium: one effect or a second oscillator.
    "warm_pad": _recipe("saw", 220.0, 0.6, (0.6, 0.5, 0.7, 0.6), cutoff=1400),
    "octave_organ": _recipe(
        "square", 293.66, 0.6, (0.01, 0.1, 0.9, 0.1), cutoff=5000, second=("sine", 2.0, 0.4)
    ),
    "gritty_bass": _recipe("saw", 110.0, 0.8, (0.005, 0.3, 0.6, 0.15), cutoff=1800, drive=0.5),
    "slap_pluck": _recipe("square", 349.23, 0.7, (0.003, 0.25, 0.1, 0.1), delay=(150, 0.3, 0.4)),
    "fuzz_lead": _recipe("square", 440.0, 0.7, (0.01, 0.2, 0.8, 0.2), cutoff=4000, drive=0.8),
    # Hard: several nodes interacting.
    "detuned_stack": _recipe(
        "saw", 146.83, 0.6, (0.03, 0.4, 0.6, 0.4), cutoff=2500, second=("saw", 1.01, 0.5)
    ),
    "dub_stab": _recipe(
        "saw", 174.61, 0.7, (0.005, 0.2, 0.2, 0.2), cutoff=1200, drive=0.3, delay=(300, 0.5, 0.5)
    ),
    "echo_stack": _recipe(
        "square",
        329.63,
        0.6,
        (0.01, 0.3, 0.4, 0.3),
        cutoff=3500,
        drive=0.2,
        delay=(220, 0.45, 0.35),
        second=("sine", 3.0, 0.3),
    ),
}


def split(name: str) -> str:
    return "held_out" if name in HELD_OUT else "dev"


def write_targets(out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, recipe in TARGETS.items():
        # FLOAT keeps the samples exact, so reference and ground truth match perfectly.
        soundfile.write(out_dir / f"{name}.wav", render(recipe), SAMPLE_RATE, subtype="FLOAT")
        manifest[name] = {"split": split(name), "recipe": recipe}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    write_targets()
    print(f"Wrote {len(TARGETS)} targets to {OUT_DIR}")
