"""Compare random, optimizer-only and AI + optimizer at the same render budget.

Hybrid runs make billed Meta API calls. Without --modes, all three modes run.

    python scripts/benchmark.py --split dev --modes random,optimizer_only
    python scripts/benchmark.py --split held_out --seeds 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import soundfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.features import Features, extract, preprocess, spectrogram_png  # noqa: E402
from app.planner import planner_from_env  # noqa: E402
from app.search import run_hybrid, run_optimizer_only, run_random  # noqa: E402

TARGET_DIR = ROOT / "data" / "targets"
RUN_DIR = ROOT / "runs"
MODES = ("random", "optimizer_only", "hybrid")
MAX_PARALLEL_HYBRID_RUNS = 4


@dataclass(frozen=True)
class Loaded:
    name: str
    features: Features
    png: bytes


def load_target(name: str) -> Loaded:
    audio, sample_rate = soundfile.read(TARGET_DIR / f"{name}.wav")
    clean = preprocess(audio, sample_rate)
    features = extract(clean, estimate_pitch=True)
    if features.f0_hz is None:
        raise SystemExit(f"{name}: no pitch found, so it can't be searched")
    return Loaded(name, features, spectrogram_png(clean))


def summarize(log: list[dict[str, Any]]) -> dict[str, Any]:
    latencies: dict[int, float] = {}
    attempts: dict[int, int] = {}
    for entry in log:
        call = entry.get("planner_call")
        if call is not None and entry.get("planner_latency_s") is not None:
            latencies[call] = entry["planner_latency_s"]
            attempts[call] = entry["planner_attempts"]
    best_entry = next((e for e in reversed(log) if e["is_best"]), None)
    return {
        "best_loss": log[-1]["best_loss"],
        "first_loss": log[0]["loss"],
        "renders": len(log),
        "failed_renders": sum(e["failure"] is not None for e in log),
        "best_source": None if best_entry is None else best_entry["source"],
        "fallback_renders": sum(e["source"] == "fallback" for e in log),
        "http_calls": sum(attempts.values()),
        "planner_seconds": round(sum(latencies.values()), 1),
    }


def decide(results: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """AI wins a target if its median best loss across seeds beats optimizer-only's."""
    per_target = {}
    for name, modes in results.items():
        medians = {
            mode: statistics.median(run["best_loss"] for run in runs)
            for mode, runs in modes.items()
        }
        per_target[name] = {"median_best_loss": medians, "ai_wins": None}
        if "hybrid" in medians and "optimizer_only" in medians:
            per_target[name]["ai_wins"] = medians["hybrid"] < medians["optimizer_only"]
    compared = [t["ai_wins"] for t in per_target.values() if t["ai_wins"] is not None]
    return {
        "per_target": per_target,
        "ai_wins": sum(compared),
        "targets_compared": len(compared),
    }


def run_mode(
    mode: str,
    loaded: Loaded,
    budget: int,
    seed: int,
    method: str,
    effort: str | None,
    run_dir: Path,
) -> dict[str, Any]:
    features = loaded.features
    path = run_dir / f"{loaded.name}-{mode}-seed{seed}.jsonl"
    if mode == "random":
        log = run_random(features, features.f0_hz, budget, seed, path)
    elif mode == "optimizer_only":
        log = run_optimizer_only(features, features.f0_hz, budget, seed, path, method)
    else:
        planner = planner_from_env(ROOT, effort)
        log = run_hybrid(features, features.f0_hz, budget, seed, planner, loaded.png, path)
    return {"seed": seed, **summarize(log)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=("dev", "held_out"), required=True)
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--budget", type=int, default=20)
    parser.add_argument("--optimizer-method", default="tpe", choices=("tpe", "restart_local"))
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--label", default=None, help="suffix for the results file")
    parser.add_argument("--subdir", default=None, help="write run logs under runs/<subdir>/")
    args = parser.parse_args()

    modes = args.modes.split(",")
    if unknown := set(modes) - set(MODES):
        print(f"Unknown modes: {', '.join(sorted(unknown))}")
        return 2
    manifest_path = TARGET_DIR / "manifest.json"
    if not manifest_path.exists():
        print("No targets found. Run: python scripts/make_targets.py")
        return 2
    manifest = json.loads(manifest_path.read_text())
    names = [name for name, entry in manifest.items() if entry["split"] == args.split]
    targets = {name: load_target(name) for name in names}

    jobs = [(mode, name, seed) for mode in modes for name in names for seed in range(args.seeds)]

    run_dir = RUN_DIR / args.subdir if args.subdir else RUN_DIR

    def work(job: tuple[str, str, int]) -> tuple[str, str, dict[str, Any]]:
        mode, name, seed = job
        run = run_mode(
            mode,
            targets[name],
            args.budget,
            seed,
            args.optimizer_method,
            args.reasoning_effort,
            run_dir,
        )
        return mode, name, run

    results: dict[str, dict[str, list[dict[str, Any]]]] = {
        name: {mode: [] for mode in modes} for name in names
    }
    with ThreadPoolExecutor(MAX_PARALLEL_HYBRID_RUNS) as pool:
        for mode, name, run in pool.map(work, jobs):
            results[name][mode].append(run)

    decision = decide(results)
    label = f"-{args.label}" if args.label else ""
    out = RUN_DIR / f"benchmark-{args.split}{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"config": vars(args), "results": results, "decision": decision}, indent=2
        )
        + "\n"
    )

    print(f"{args.split}: median best normalized loss, budget {args.budget}, {args.seeds} seed(s)")
    print(f"{'target':<16}" + "".join(f"{mode:>16}" for mode in modes) + "  AI wins")
    for name, row in decision["per_target"].items():
        medians = "".join(f"{row['median_best_loss'][mode]:>16.4f}" for mode in modes)
        print(f"{name:<16}{medians}  {row['ai_wins']}")
    if decision["targets_compared"]:
        print(f"\nAI + optimizer wins {decision['ai_wins']} of {decision['targets_compared']} targets.")
    if "hybrid" in modes:
        runs = [run for modes_ in results.values() for run in modes_["hybrid"]]
        print(
            f"Hybrid: {sum(r['http_calls'] for r in runs)} HTTP calls, "
            f"{sum(r['fallback_renders'] > 0 for r in runs)} of {len(runs)} runs used the fallback, "
            f"planner time per run {statistics.median(r['planner_seconds'] for r in runs):.0f} s (median)."
        )
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
