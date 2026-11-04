"""Benchmark: the go/no-go decision rule, run summaries and the command line."""

import json

import pytest

import scripts.benchmark as benchmark
from scripts.make_targets import write_targets


def runs(*losses):
    return [{"best_loss": loss} for loss in losses]


def test_ai_wins_only_when_its_median_is_strictly_lower():
    decision = benchmark.decide(
        {
            "a": {"hybrid": runs(0.1, 0.2, 0.3), "optimizer_only": runs(0.3, 0.3, 0.3)},
            "b": {"hybrid": runs(0.3, 0.3, 0.3), "optimizer_only": runs(0.3, 0.3, 0.3)},
            "c": {"hybrid": runs(0.5, 0.5, 0.01), "optimizer_only": runs(0.2, 0.2, 0.2)},
        }
    )
    assert decision["per_target"]["a"]["ai_wins"] is True
    assert decision["per_target"]["b"]["ai_wins"] is False
    # One lucky seed doesn't win a target.
    assert decision["per_target"]["c"]["ai_wins"] is False
    assert decision["ai_wins"] == 1 and decision["targets_compared"] == 3


def test_no_comparison_without_both_modes():
    decision = benchmark.decide({"a": {"random": runs(0.1)}})
    assert decision["targets_compared"] == 0 and decision["per_target"]["a"]["ai_wins"] is None


def test_summary_counts_calls_once_per_planner_call():
    entry = {"loss": 0.5, "best_loss": 0.5, "failure": None, "is_best": False}
    log = [
        {**entry, "source": "model", "planner_call": 1, "planner_latency_s": 28.0, "planner_attempts": 2},
        {**entry, "source": "model", "planner_call": 1, "planner_latency_s": 28.0, "planner_attempts": 2, "is_best": True},
        {**entry, "source": "optimizer", "planner_call": 1},
        {**entry, "source": "fallback", "planner_call": 2, "planner_latency_s": 1.0, "planner_attempts": 1},
    ]
    summary = benchmark.summarize(log)
    assert summary["http_calls"] == 3 and summary["planner_seconds"] == 29.0
    assert summary["fallback_renders"] == 1 and summary["best_source"] == "model"


def test_summary_of_all_failed_renders():
    log = [{"loss": None, "best_loss": None, "failure": "x", "is_best": False, "source": "optimizer"}]
    summary = benchmark.summarize(log)
    assert summary["best_loss"] is None and summary["failed_renders"] == 1 and summary["best_source"] is None


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    targets = tmp_path / "targets"
    write_targets(targets)
    monkeypatch.setattr(benchmark, "TARGET_DIR", targets)
    monkeypatch.setattr(benchmark, "RUN_DIR", tmp_path / "runs")
    return tmp_path


def run(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["benchmark.py", *args])
    return benchmark.main()


def test_offline_modes_use_only_the_chosen_split_and_no_planner(workspace, monkeypatch, capsys):
    def forbidden(*args):
        raise AssertionError("no planner without hybrid mode")

    monkeypatch.setattr(benchmark, "planner_from_env", forbidden)
    assert run(monkeypatch, "--split", "held_out", "--modes", "random,optimizer_only", "--seeds", "2", "--budget", "4") == 0
    saved = json.loads((workspace / "runs" / "benchmark-held_out.json").read_text())
    assert set(saved["results"]) == {"glass_pluck", "fuzz_lead", "echo_stack"}
    assert len(saved["results"]["fuzz_lead"]["random"]) == 2
    assert (workspace / "runs" / "fuzz_lead-optimizer_only-seed1.jsonl").exists()
    assert "accuracy" not in capsys.readouterr().out.lower()


def test_subdir_keeps_logs_apart(workspace, monkeypatch):
    assert run(monkeypatch, "--split", "dev", "--modes", "random", "--seeds", "1", "--budget", "2", "--subdir", "x") == 0
    assert (workspace / "runs" / "x" / "soft_sine-random-seed0.jsonl").exists()
    assert not (workspace / "runs" / "soft_sine-random-seed0.jsonl").exists()


def test_unknown_mode_is_refused(workspace, monkeypatch):
    assert run(monkeypatch, "--split", "dev", "--modes", "magic") == 2


def test_missing_targets_explain_what_to_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "TARGET_DIR", tmp_path / "none")
    assert run(monkeypatch, "--split", "dev") == 2
    assert "make_targets" in capsys.readouterr().out
