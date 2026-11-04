"""Run the random-search baseline on the dev targets and print best-so-far loss curves.

Held-out targets are refused unless --allow-held-out is given.

    python scripts/make_targets.py
    python scripts/loss_curve.py
    python scripts/loss_curve.py --target warm_pad --budget 50
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path

import soundfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dsp import render  # noqa: E402
from app.features import extract, preprocess  # noqa: E402
from app.loss import compare  # noqa: E402
from app.search import run_random  # noqa: E402

TARGET_DIR = ROOT / "data" / "targets"
RUN_DIR = ROOT / "runs"
BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], low: float, high: float) -> str:
    span = (high - low) or 1.0
    return "".join(BARS[round((v - low) / span * (len(BARS) - 1))] for v in values)


def run_target(name: str, entry: dict, budget: int, seed: int) -> dict:
    audio, sample_rate = soundfile.read(TARGET_DIR / f"{name}.wav")
    features = extract(preprocess(audio, sample_rate), estimate_pitch=True)
    if features.f0_hz is None:
        raise SystemExit(f"{name}: no pitch found, so it can't be searched")

    log = run_random(
        features, features.f0_hz, budget, seed, RUN_DIR / f"{name}-random-seed{seed}.jsonl"
    )
    true_recipe = copy.deepcopy(entry["recipe"])
    true_recipe["oscillator"]["frequency_hz"] = features.f0_hz
    floor = compare(features, extract(render(true_recipe))).loss
    return {
        "name": name,
        "split": entry["split"],
        "f0": features.f0_hz,
        "true_f0": entry["recipe"]["oscillator"]["frequency_hz"],
        "curve": [e["best_loss"] for e in log],
        "floor": floor,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", help="one target name; default is all dev targets")
    parser.add_argument("--budget", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--allow-held-out", action="store_true")
    args = parser.parse_args()

    manifest_path = TARGET_DIR / "manifest.json"
    if not manifest_path.exists():
        print("No targets found. Run: python scripts/make_targets.py")
        return 2
    manifest = json.loads(manifest_path.read_text())

    if args.target:
        if args.target not in manifest:
            print(f"Unknown target {args.target}. Choose from: {', '.join(manifest)}")
            return 2
        if manifest[args.target]["split"] == "held_out" and not args.allow_held_out:
            print(f"{args.target} is held out. Pass --allow-held-out only for final evaluation.")
            return 2
        names = [args.target]
    else:
        names = [name for name, entry in manifest.items() if entry["split"] == "dev"]

    results = [run_target(n, manifest[n], args.budget, args.seed) for n in names]
    low = min(min(r["curve"]) for r in results)
    high = max(r["curve"][0] for r in results)

    print(f"Random search, best-so-far loss, budget {args.budget}, seed {args.seed}\n")
    print(f"{'target':<16}{'f0 true/est':>16}{'first':>8}{'best':>8}{'truth':>8}  curve")
    for r in results:
        pitch = f"{r['true_f0']:.1f}/{r['f0']:.1f}"
        curve = sparkline(r["curve"], low, high)
        print(
            f"{r['name']:<16}{pitch:>16}{r['curve'][0]:>8.3f}{r['curve'][-1]:>8.3f}"
            f"{r['floor']:>8.3f}  {curve}"
        )
    print(f"\nMedian best loss: {statistics.median(r['curve'][-1] for r in results):.3f}")
    print("truth = loss of the ground-truth recipe rendered at the estimated pitch")
    print(f"Logs: {RUN_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
