"""Synthetic reference set: size, split, validity and exact round trip."""

import json

import numpy as np
import soundfile

from app.dsp import render
from app.schema import SAMPLE_RATE, validate_recipe
from scripts.make_targets import HELD_OUT, TARGETS, split, write_targets


def test_set_size_matches_the_spec():
    assert 8 <= len(TARGETS) <= 12


def test_three_held_out_targets_exist():
    assert len(HELD_OUT) == 3 and set(HELD_OUT) <= set(TARGETS)


def test_every_recipe_is_valid():
    for name, recipe in TARGETS.items():
        assert validate_recipe(recipe) == [], name


def test_held_out_covers_easy_medium_and_hard():
    nodes = [
        sum(TARGETS[n][k] is not None for k in ("oscillator_2", "filter", "distortion", "delay"))
        for n in HELD_OUT
    ]
    assert len(set(nodes)) == 3


def test_every_node_appears_in_the_dev_set():
    dev = [r for name, r in TARGETS.items() if split(name) == "dev"]
    for node in ("oscillator_2", "filter", "distortion", "delay"):
        assert any(r[node] is not None for r in dev), node


def test_written_files_round_trip_exactly(tmp_path):
    write_targets(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest) == set(TARGETS)
    for name, entry in manifest.items():
        assert entry["split"] == split(name)
        assert entry["recipe"] == TARGETS[name]
        audio, rate = soundfile.read(tmp_path / f"{name}.wav")
        assert rate == SAMPLE_RATE
        assert np.max(np.abs(audio - render(TARGETS[name]))) < 1e-6
