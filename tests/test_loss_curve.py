"""Loss-curve script: output, split protection and missing-data handling."""

import json

import pytest

import scripts.loss_curve as loss_curve
from scripts.make_targets import write_targets


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    targets = tmp_path / "targets"
    write_targets(targets)
    manifest = json.loads((targets / "manifest.json").read_text())
    keep = {"soft_sine", "glass_pluck"}
    (targets / "manifest.json").write_text(json.dumps({k: manifest[k] for k in keep}))
    monkeypatch.setattr(loss_curve, "TARGET_DIR", targets)
    monkeypatch.setattr(loss_curve, "RUN_DIR", tmp_path / "runs")
    return tmp_path


def run(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["loss_curve.py", *args])
    return loss_curve.main()


def test_sparkline_runs_from_lowest_to_highest_bar():
    assert loss_curve.sparkline([1.0, 0.0], 0.0, 1.0) == "█▁"


def test_sparkline_with_a_flat_curve():
    assert loss_curve.sparkline([0.5, 0.5], 0.5, 0.5) == "▁▁"


def test_default_runs_dev_only_and_writes_a_log(workspace, monkeypatch, capsys):
    assert run(monkeypatch, "--budget", "3") == 0
    out = capsys.readouterr().out
    assert "soft_sine" in out and "glass_pluck" not in out
    assert len((workspace / "runs" / "soft_sine-random-seed0.jsonl").read_text().splitlines()) == 3


def test_held_out_target_is_refused_without_the_flag(workspace, monkeypatch, capsys):
    assert run(monkeypatch, "--target", "glass_pluck", "--budget", "2") == 2
    assert "held out" in capsys.readouterr().out
    assert not (workspace / "runs").exists()


def test_held_out_target_runs_with_the_flag(workspace, monkeypatch):
    assert run(monkeypatch, "--target", "glass_pluck", "--budget", "2", "--allow-held-out") == 0


def test_unknown_target_is_refused(workspace, monkeypatch, capsys):
    assert run(monkeypatch, "--target", "nope") == 2
    assert "Unknown target" in capsys.readouterr().out


def test_missing_targets_explain_what_to_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loss_curve, "TARGET_DIR", tmp_path / "empty")
    assert run(monkeypatch) == 2
    assert "make_targets" in capsys.readouterr().out
