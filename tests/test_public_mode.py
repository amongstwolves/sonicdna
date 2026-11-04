"""The public deployment: no model calls, nothing stored from visitors, frontend served."""

import io
from pathlib import Path

import pytest
import soundfile
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import api
from app.schema import SAMPLE_RATE
from scripts.make_targets import write_targets
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
client = TestClient(api.app)


@pytest.fixture
def public(tmp_path, monkeypatch):
    write_targets(tmp_path / "targets")
    monkeypatch.setenv("SONICDNA_PUBLIC", "1")
    monkeypatch.setenv("SONICDNA_TARGETS_DIR", str(tmp_path / "targets"))
    monkeypatch.setenv("SONICDNA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("SONICDNA_LIVE_DIR", str(tmp_path / "live"))
    api._LIVE_RUNS.clear()
    yield tmp_path
    api._LIVE_RUNS.clear()


def wav_bytes():
    buffer = io.BytesIO()
    t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
    soundfile.write(buffer, 0.5 * np.sin(2 * np.pi * 220 * t), SAMPLE_RATE, format="WAV")
    return buffer.getvalue()


def test_meta_reports_public_mode(public, monkeypatch):
    assert client.get("/api/meta").json()["public_mode"] is True
    monkeypatch.delenv("SONICDNA_PUBLIC")
    assert client.get("/api/meta").json()["public_mode"] is False


def test_ai_run_is_refused_even_when_a_key_is_present(public, monkeypatch):
    def must_not_run(_root):
        raise AssertionError("public mode must never build a planner")

    monkeypatch.setenv("META_API_KEY", "not-a-real-key")
    monkeypatch.setattr(api, "planner_from_env", must_not_run)
    response = client.post("/api/runs", json={"target": "echo_stack", "mode": "hybrid"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ai_runs_disabled"
    assert api._LIVE_RUNS == {} and not (public / "live").exists()


def test_upload_is_refused_and_nothing_is_stored(public):
    files = {"file": ("sound.wav", wav_bytes(), "audio/wav")}
    response = client.post("/api/analyze", files=files)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "uploads_disabled"
    assert not (public / "live").exists()


def test_private_mode_still_accepts_uploads(public, monkeypatch):
    monkeypatch.delenv("SONICDNA_PUBLIC")
    files = {"file": ("sound.wav", wav_bytes(), "audio/wav")}
    assert client.post("/api/analyze", files=files).status_code == 200


def test_repeat_target_analysis_is_not_recomputed(public, monkeypatch):
    api._target_analysis_cached.cache_clear()
    calls = []
    real = api._analysis
    monkeypatch.setattr(api, "_analysis", lambda audio: calls.append(1) or real(audio))
    first = client.get("/api/targets/echo_stack/analysis").json()
    second = client.get("/api/targets/echo_stack/analysis").json()
    assert first == second and len(calls) == 1


def test_frontend_is_served_and_api_routes_still_win(tmp_path):
    (tmp_path / "index.html").write_text("home")
    (tmp_path / "lab").mkdir()
    (tmp_path / "lab" / "index.html").write_text("lab page")
    site = FastAPI()
    site.include_router(api.app.router)
    api.mount_frontend(site, str(tmp_path))
    served = TestClient(site)
    assert served.get("/").text == "home"
    assert served.get("/lab/").text == "lab page"
    assert served.get("/lab").text == "lab page"
    assert served.get("/api/health").json() == {"status": "ok"}
    assert served.get("/missing/").status_code == 404


def test_deploy_files_cannot_carry_the_key():
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".env" in ignored
    assert "META_API_KEY" not in (ROOT / "Dockerfile").read_text()
    assert "SONICDNA_PUBLIC=1" in (ROOT / "Dockerfile").read_text()
    blueprint = [l for l in (ROOT / "render.yaml").read_text().splitlines() if not l.startswith("#")]
    assert not any("META_API_KEY" in line for line in blueprint)
