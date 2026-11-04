"""Numeric search: stays in bounds, keeps structure, and improves on a real target."""

import copy

import numpy as np
import pytest

from app.dsp import render
from app.features import extract
from app.loss import compare
from app.optimizer import LocalSearch, TpeSearch, continuous_paths
from app.schema import to_recipe, validate_recipe
from scripts.make_targets import TARGETS

RECIPE = TARGETS["warm_pad"]


def test_continuous_paths_skip_switched_off_nodes():
    paths = continuous_paths(RECIPE)
    assert "filter.cutoff_hz" in paths and "delay.wet" not in paths
    assert "oscillator.frequency_hz" not in paths


def test_gain_is_not_tuned_when_it_would_change_nothing():
    alone = copy.deepcopy(RECIPE)
    assert "oscillator.gain" not in continuous_paths(alone)
    louder = copy.deepcopy(alone)
    louder["oscillator"]["gain"] = 0.2
    assert np.allclose(render(alone), render(louder))


@pytest.mark.parametrize(
    "node, value",
    [
        ("distortion", {"drive": 0.5}),
        ("oscillator_2", {"type": "sine", "gain": 0.5, "frequency_ratio": 2.0}),
    ],
)
def test_gain_is_tuned_when_it_matters(node, value):
    recipe = copy.deepcopy(RECIPE)
    recipe[node] = value
    assert "oscillator.gain" in continuous_paths(recipe)
    louder = copy.deepcopy(recipe)
    louder["oscillator"]["gain"] = 0.2
    assert not np.allclose(render(recipe), render(louder))


def test_local_search_never_changes_structure_or_pitch():
    search = LocalSearch(RECIPE, 1.0, np.random.default_rng(0))
    search.step = 0.5
    for _ in range(100):
        proposal = search.propose()
        assert validate_recipe(proposal) == []
        assert proposal["oscillator"]["type"] == "saw"
        assert proposal["oscillator"]["frequency_hz"] == RECIPE["oscillator"]["frequency_hz"]
        assert proposal["distortion"] is None and proposal["delay"] is None


def test_local_search_changes_something_without_touching_the_original():
    before = copy.deepcopy(RECIPE)
    assert LocalSearch(RECIPE, 1.0, np.random.default_rng(0)).propose() != before
    assert RECIPE == before


def test_local_search_keeps_the_better_recipe_and_adapts_its_step():
    search = LocalSearch(RECIPE, 1.0, np.random.default_rng(0))
    start = search.step
    worse = search.propose()
    search.report(worse, 2.0)
    assert search.best == RECIPE and search.best_loss == 1.0 and search.step < start
    better = search.propose()
    step = search.step
    search.report(better, 0.5)
    assert search.best == better and search.best_loss == 0.5 and search.step > step


def test_local_search_treats_a_failed_render_as_no_improvement():
    search = LocalSearch(RECIPE, 1.0, np.random.default_rng(0))
    search.report(search.propose(), None)
    assert search.best_loss == 1.0


def test_local_search_is_seeded():
    first = LocalSearch(RECIPE, 1.0, np.random.default_rng(3)).propose()
    assert first == LocalSearch(RECIPE, 1.0, np.random.default_rng(3)).propose()


def test_local_search_improves_a_detuned_start():
    target = extract(render(RECIPE))
    start = copy.deepcopy(RECIPE)
    start["filter"]["cutoff_hz"] = 5000.0
    start["envelope"]["attack_s"] = 0.05
    start_loss = compare(target, extract(render(start))).loss
    search = LocalSearch(start, start_loss, np.random.default_rng(0))
    for _ in range(40):
        proposal = search.propose()
        search.report(proposal, compare(target, extract(render(proposal))).loss)
    assert search.best_loss < start_loss / 2


def test_tpe_proposals_are_valid_and_vary_structure():
    tpe = TpeSearch(0)
    seen = set()
    for _ in range(25):
        recipe = to_recipe(tpe.propose(), 220.0, 1.0)
        assert validate_recipe(recipe) == []
        seen.add(tuple(recipe[n] is None for n in ("oscillator_2", "filter", "distortion", "delay")))
        tpe.report(float(np.random.default_rng(len(seen)).random()))
    assert len(seen) > 1


def test_tpe_is_seeded():
    def draw(seed):
        tpe = TpeSearch(seed)
        recipes = []
        for i in range(8):
            recipes.append(tpe.propose())
            tpe.report(1.0 / (i + 1))
        return recipes

    assert draw(1) == draw(1)
    assert draw(1) != draw(2)


def test_tpe_accepts_a_failed_render():
    tpe = TpeSearch(0)
    tpe.propose()
    tpe.report(None)
    assert validate_recipe(to_recipe(tpe.propose(), 220.0, 1.0)) == []


def test_tpe_beats_its_own_first_guess_on_a_real_target():
    target = extract(render(RECIPE))
    tpe = TpeSearch(0)
    losses = []
    for _ in range(30):
        loss = compare(target, extract(render(to_recipe(tpe.propose(), 220.0, target.duration_s)))).loss
        tpe.report(loss)
        losses.append(loss)
    assert min(losses) < losses[0]
