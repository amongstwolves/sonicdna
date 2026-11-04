"""Hybrid and optimizer-only loops: budget, provenance, caps and failure handling."""

import numpy as np
import pytest

import app.search as search
from app.dsp import render
from app.features import extract
from app.planner import PlannerResult, fallback_candidates
from app.search import run_hybrid, run_optimizer_only
from scripts.make_targets import TARGETS

RECIPE = TARGETS["warm_pad"]
PITCH = RECIPE["oscillator"]["frequency_hz"]


@pytest.fixture(scope="module")
def target():
    return extract(render(RECIPE))


def model_candidates(n, kind="saw", cutoff=1000.0):
    return [
        {
            "hypothesis": f"Hypothesis {i}",
            "proposed_recipe_or_delta": {
                "oscillator": {"type": kind, "gain": 0.7},
                "oscillator_2": None,
                "envelope": {"attack_s": 0.5, "decay_s": 0.5, "sustain": 0.7, "release_s": 0.5},
                "filter": {"type": "lowpass", "cutoff_hz": cutoff + 100 * i},
                "distortion": None,
                "delay": None,
            },
            "expected_effect": "Closer.",
            "rationale": "Because.",
        }
        for i in range(n)
    ]


class FakePlanner:
    def __init__(self, results=None, n=4, max_calls=4):
        self.results = results
        self.n = n
        self.max_calls = max_calls
        self.calls_made = 0
        self.contexts = []

    @property
    def can_call(self):
        return self.calls_made < self.max_calls

    def plan(self, context):
        self.calls_made += 1
        self.contexts.append(context)
        if self.results is not None:
            return self.results.pop(0)
        return PlannerResult("model", "propose_structure", model_candidates(self.n), 1, 28.0)


def fallback_result(attempts=2):
    return PlannerResult("fallback", "propose_structure", fallback_candidates({}), attempts, 0.1, error="HTTP 500")


@pytest.mark.parametrize("budget", [1, 4, 5, 7, 20, 33])
def test_hybrid_spends_the_budget_exactly(target, budget):
    assert len(run_hybrid(target, PITCH, budget, 0, FakePlanner())) == budget


def test_hybrid_never_exceeds_four_planner_calls(target):
    planner = FakePlanner(n=3)
    run_hybrid(target, PITCH, 200, 0, planner)
    assert planner.calls_made == 4


def test_every_render_records_where_it_came_from(target):
    log = run_hybrid(target, PITCH, 20, 0, FakePlanner())
    assert {e["source"] for e in log} == {"model", "optimizer"}
    for entry in log:
        assert entry["mode"] == "hybrid"
        if entry["source"] == "model":
            assert entry["hypothesis"] and entry["rationale"] and entry["expected_effect"]
            assert entry["planner_call"] >= 1 and entry["planner_latency_s"] == 28.0
        else:
            assert entry["hypothesis"] is None


def test_optimizer_runs_between_planner_calls(target):
    log = run_hybrid(target, PITCH, 20, 0, FakePlanner(n=4), refine_per_round=3)
    sources = [e["source"] for e in log]
    assert sources[:7] == ["model"] * 4 + ["optimizer"] * 3
    assert sources[7:11] == ["model"] * 4
    assert [e["planner_call"] for e in log[:11]] == [1] * 7 + [2] * 4


def test_optimizer_keeps_the_structure_it_is_tuning(target):
    log = run_hybrid(target, PITCH, 20, 0, FakePlanner(n=3))
    for entry in log:
        assert entry["recipe"]["distortion"] is None and entry["recipe"]["delay"] is None


def test_pitch_comes_from_the_estimate_on_every_render(target):
    for entry in run_hybrid(target, 123.0, 12, 0, FakePlanner()):
        assert entry["recipe"]["oscillator"]["frequency_hz"] == 123.0


def test_best_so_far_never_gets_worse(target):
    best = [e["best_loss"] for e in run_hybrid(target, PITCH, 20, 0, FakePlanner())]
    assert best == sorted(best, reverse=True)


def test_later_calls_see_the_best_recipe_and_recent_results(target):
    planner = FakePlanner(n=3)
    log = run_hybrid(target, PITCH, 20, 0, planner, spectrogram_png=b"png")
    first, second = planner.contexts[:2]
    assert first.best_recipe is None and first.recent == [] and first.remaining_budget == 20
    assert first.spectrogram_png == b"png"
    assert second.best_loss == min(e["loss"] for e in log[:6])
    assert "frequency_hz" not in second.best_recipe["oscillator"]
    assert second.recent[-1]["normalized_loss"] == log[5]["loss"]
    assert second.remaining_budget == 14


def test_fallback_is_labelled_and_stops_further_calls(target):
    planner = FakePlanner(results=[fallback_result()])
    log = run_hybrid(target, PITCH, 20, 0, planner)
    assert planner.calls_made == 1 and len(log) == 20
    assert {e["source"] for e in log[:3]} == {"fallback"}
    assert log[0]["planner_error"] == "HTTP 500" and log[0]["planner_attempts"] == 2
    assert {e["source"] for e in log[3:]} == {"optimizer"}


def test_stop_action_hands_the_rest_to_the_optimizer(target):
    results = [
        PlannerResult("model", "propose_structure", model_candidates(3), 1, 1.0),
        PlannerResult("model", "stop", [], 1, 1.0),
    ]
    planner = FakePlanner(results=results)
    log = run_hybrid(target, PITCH, 20, 0, planner)
    assert planner.calls_made == 2 and len(log) == 20
    assert {e["source"] for e in log[3:]} == {"optimizer"}


def test_immediate_stop_still_spends_the_budget_on_a_labelled_source(target):
    planner = FakePlanner(results=[PlannerResult("model", "stop", [], 1, 1.0)])
    log = run_hybrid(target, PITCH, 8, 0, planner)
    assert len(log) == 8 and log[0]["source"] == "fallback"
    assert log[-1]["best_loss"] is not None


def test_candidates_are_cut_to_the_remaining_budget(target):
    assert len(run_hybrid(target, PITCH, 5, 0, FakePlanner(n=5))) == 5


def test_no_planner_call_when_too_little_budget_remains(target):
    planner = FakePlanner()
    run_hybrid(target, PITCH, 4, 0, planner)
    assert planner.calls_made == 0


def test_all_renders_failing_still_ends_cleanly(target, monkeypatch):
    def broken(recipe):
        raise ValueError("boom")

    monkeypatch.setattr(search, "render", broken)
    log = run_hybrid(target, PITCH, 10, 0, FakePlanner())
    assert len(log) == 10 and all(e["failure"] == "boom" for e in log)
    assert all(e["best_loss"] is None for e in log)


def test_hybrid_optimizer_steps_are_seeded(target):
    def losses(seed):
        return [e["loss"] for e in run_hybrid(target, PITCH, 15, seed, FakePlanner())]

    assert losses(1) == losses(1) and losses(1) != losses(2)


@pytest.mark.parametrize("method", ["tpe", "restart_local"])
def test_optimizer_only_uses_no_model_and_spends_the_budget(target, method):
    log = run_optimizer_only(target, PITCH, 20, 0, method=method)
    assert len(log) == 20
    assert {e["source"] for e in log} == {"optimizer"} and {e["mode"] for e in log} == {"optimizer_only"}
    assert all(e["planner_call"] is None and e["hypothesis"] is None for e in log)
    best = [e["best_loss"] for e in log]
    assert best == sorted(best, reverse=True) and best[-1] < log[0]["loss"]


@pytest.mark.parametrize("method", ["tpe", "restart_local"])
def test_optimizer_only_is_seeded_and_writes_a_log(target, method, tmp_path):
    path = tmp_path / "run.jsonl"
    first = run_optimizer_only(target, PITCH, 10, 3, path, method)
    assert [e["loss"] for e in first] == [e["loss"] for e in run_optimizer_only(target, PITCH, 10, 3, method=method)]
    assert len(path.read_text().splitlines()) == 10


def test_unknown_method_is_refused(target):
    with pytest.raises(ValueError, match="unknown optimizer method"):
        run_optimizer_only(target, PITCH, 5, 0, method="magic")


def test_hybrid_log_file_is_written(target, tmp_path):
    path = tmp_path / "hybrid.jsonl"
    run_hybrid(target, PITCH, 5, 0, FakePlanner(), log_path=path)
    assert len(path.read_text().splitlines()) == 5
