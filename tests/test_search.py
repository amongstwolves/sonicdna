"""Random-search baseline and experiment log."""

import copy
import json

import numpy as np
import pytest

import app.search as search
from app.dsp import render
from app.features import extract
from app.loss import compare
from app.schema import validate_recipe
from app.search import run_random, sample_planner_recipe
from scripts.make_targets import TARGETS

RECIPE = TARGETS["warm_pad"]
PITCH = RECIPE["oscillator"]["frequency_hz"]


@pytest.fixture(scope="module")
def target():
    return extract(render(RECIPE))


def test_samples_are_always_renderable():
    rng = np.random.default_rng(0)
    for _ in range(300):
        planner = sample_planner_recipe(rng)
        recipe = search.to_recipe(planner, 220.0, 1.0)
        assert validate_recipe(recipe) == []


def test_sampling_covers_every_type_and_node_state():
    rng = np.random.default_rng(0)
    samples = [sample_planner_recipe(rng) for _ in range(200)]
    assert {s["oscillator"]["type"] for s in samples} == {"sine", "saw", "square"}
    for node in ("oscillator_2", "filter", "distortion", "delay"):
        assert {s[node] is None for s in samples} == {True, False}


def test_same_seed_repeats_and_different_seed_differs(target):
    def losses(seed):
        return [e["loss"] for e in run_random(target, PITCH, 5, seed)]

    assert losses(1) == losses(1)
    assert losses(1) != losses(2)


def test_budget_is_exact(target):
    assert len(run_random(target, PITCH, 7, 0)) == 7


def test_best_so_far_never_gets_worse_and_matches_the_log(target):
    log = run_random(target, PITCH, 30, 0)
    best = [e["best_loss"] for e in log]
    assert best == sorted(best, reverse=True)
    assert best[-1] == min(e["loss"] for e in log)
    assert log[0]["is_best"]
    for entry in log:
        assert entry["is_best"] == (entry["loss"] == entry["best_loss"])


def test_log_entries_are_reproducible_evidence(target):
    entry = run_random(target, PITCH, 1, 0)[0]
    assert set(entry) >= {
        "index", "timestamp", "mode", "seed", "source", "recipe",
        "loss", "components", "score", "failure", "is_best", "best_loss",
    }
    # The logged recipe alone reproduces the logged score.
    assert compare(target, extract(render(entry["recipe"]))).loss == entry["loss"]


def test_pitch_is_never_sampled(target):
    for entry in run_random(target, 123.0, 10, 0):
        assert entry["recipe"]["oscillator"]["frequency_hz"] == 123.0


def test_log_file_is_json_lines(target, tmp_path):
    path = tmp_path / "nested" / "run.jsonl"
    log = run_random(target, PITCH, 3, 0, path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines == json.loads(json.dumps(log))


def test_failed_render_is_logged_and_the_search_carries_on(target, monkeypatch):
    real = search.render
    calls = {"n": 0}

    def flaky(recipe):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("boom")
        return real(recipe)

    monkeypatch.setattr(search, "render", flaky)
    log = run_random(target, PITCH, 4, 0)
    assert len(log) == 4
    assert log[1]["failure"] == "boom" and log[1]["loss"] is None and not log[1]["is_best"]
    assert log[2]["failure"] is None and log[1]["best_loss"] == log[0]["best_loss"]


def test_all_failures_leave_no_best(target, monkeypatch):
    def broken(recipe):
        raise ValueError("boom")

    monkeypatch.setattr(search, "render", broken)
    log = run_random(target, PITCH, 2, 0)
    assert all(e["best_loss"] is None for e in log)


@pytest.mark.parametrize("name", ["warm_pad", "gritty_bass"])
def test_truth_beats_a_much_larger_random_search(name):
    # If this failed, the loss would be pulling the search away from the right answer.
    recipe = TARGETS[name]
    target = extract(render(recipe))
    log = run_random(target, recipe["oscillator"]["frequency_hz"], 150, 0)
    best = log[-1]["best_loss"]
    assert compare(target, extract(render(copy.deepcopy(recipe)))).loss == 0
    assert best > 0
    assert best < log[0]["loss"]
