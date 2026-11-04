"""Committed demo evidence: the replay log, its WAVs, and the held-out chart."""

import json
import re
import statistics
import subprocess
from pathlib import Path

import numpy as np
import soundfile

from app.dsp import render
from app.features import extract, preprocess
from app.loss import compare
from scripts.make_chart import CHART, RESULTS, RULE, build_svg, verdicts
from scripts.make_targets import TARGETS, write_targets

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "demo" / "echo_stack-hybrid-seed2.jsonl"


def log():
    return [json.loads(line) for line in RUN.read_text().splitlines()]


def test_demo_run_is_a_complete_real_hybrid_run():
    entries = log()
    assert len(entries) == 20 and {e["source"] for e in entries} == {"model", "optimizer"}
    assert all(e["mode"] == "hybrid" and e["failure"] is None for e in entries)
    assert 1 <= max(e["planner_call"] for e in entries) <= 4
    assert all(e["hypothesis"] for e in entries if e["source"] == "model")


def test_demo_run_rescores_exactly_against_a_regenerated_target(tmp_path):
    write_targets(tmp_path)
    audio, rate = soundfile.read(tmp_path / "echo_stack.wav")
    target = extract(preprocess(audio, rate))
    for entry in log():
        assert compare(target, extract(render(entry["recipe"]))).loss == entry["loss"]


def test_committed_wavs_match_the_run():
    best = next(e for e in reversed(log()) if e["is_best"])
    reference, _ = soundfile.read(ROOT / "demo" / "echo_stack_reference.wav")
    audio, _ = soundfile.read(ROOT / "demo" / "echo_stack_best.wav")
    assert np.max(np.abs(audio - render(best["recipe"]))) < 1e-5
    assert np.max(np.abs(reference - preprocess(render(TARGETS["echo_stack"]), 44100))) < 1e-5


def test_regenerating_targets_gives_identical_audio(tmp_path):
    write_targets(tmp_path / "a")
    write_targets(tmp_path / "b")
    for name in TARGETS:
        first, _ = soundfile.read(tmp_path / "a" / f"{name}.wav")
        second, _ = soundfile.read(tmp_path / "b" / f"{name}.wav")
        assert np.array_equal(first, second)


def test_demo_files_are_not_gitignored():
    for name in ("echo_stack_best.wav", "echo_stack_reference.wav", "echo_stack-hybrid-seed2.jsonl"):
        ignored = subprocess.run(["git", "check-ignore", "-q", f"demo/{name}"], cwd=ROOT)
        assert ignored.returncode == 1, name


def test_other_wavs_stay_ignored():
    assert subprocess.run(["git", "check-ignore", "-q", "listen/x.wav"], cwd=ROOT).returncode == 0


def results():
    return json.loads(RESULTS.read_text())


def test_recorded_result_matches_the_go_no_go():
    wins = verdicts(results())
    assert wins == {"glass_pluck": False, "fuzz_lead": False, "echo_stack": True}


def test_demo_run_is_the_median_seed_not_the_best():
    seeds = results()["targets"]["echo_stack"]["hybrid"]
    assert log()[-1]["best_loss"] == statistics.median(seeds) != min(seeds)


def test_verdict_needs_to_beat_both_optimizers():
    data = {"targets": {"t": {"hybrid": [0.2], "tpe": [0.3], "restart_local": [0.1], "random": [0.9]}}}
    assert verdicts(data) == {"t": False}


def test_chart_is_current_honest_and_uses_the_right_words():
    svg = build_svg(results())
    assert CHART.read_text() == svg
    assert "won 1 of 3" in svg and "normalized loss" in svg and RULE in svg
    assert not re.search(r"accura|%\s|\d%|identical", svg.lower().split("</style>")[1])
