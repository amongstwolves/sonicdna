"""Live runs, stored uploads and Alchemy through the API. No billed calls."""

import base64
import io
import time

import numpy as np
import pytest
import soundfile
from fastapi.testclient import TestClient

import app.api as api
from app.dsp import oscillator
from app.planner import PlannerResult
from app.schema import SAMPLE_RATE
from scripts.make_targets import TARGETS, write_targets

client = TestClient(api.app)
RECIPE = TARGETS["warm_pad"]


class FakePlanner:
    can_call = True

    def __init__(self, release=None):
        self.release = release

    def plan(self, context):
        if self.release is not None:
            self.release.wait(5)
        recipe = {k: v for k, v in RECIPE.items() if k not in ("schema_version", "sample_rate", "duration_s")}
        recipe = {**recipe, "oscillator": {"type": "saw", "gain": 0.6}}
        candidates = [
            {"hypothesis": "A saw.", "proposed_recipe_or_delta": recipe, "expected_effect": "Closer.", "rationale": "Harmonics."}
            for _ in range(3)
        ]
        return PlannerResult("model", "propose_structure", candidates, 1, 0.01)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    write_targets(tmp_path / "targets")
    (tmp_path / "runs").mkdir()
    monkeypatch.setenv("SONICDNA_TARGETS_DIR", str(tmp_path / "targets"))
    monkeypatch.setenv("SONICDNA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("SONICDNA_LIVE_DIR", str(tmp_path / "live"))
    api._LIVE_RUNS.clear()
    yield tmp_path
    wait_until_idle()
    api._LIVE_RUNS.clear()


def wait_until_idle(timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(run["status"] == "running" for run in api._LIVE_RUNS.values()):
            return
        time.sleep(0.02)
    raise AssertionError("live run did not finish")


def start(**body):
    return client.post("/api/runs", json={"target": "warm_pad", "budget": 8, **body})


def use_planner(monkeypatch, planner):
    monkeypatch.setattr(api, "planner_from_env", lambda root: planner)


def test_hybrid_run_logs_real_entries_and_reports_as_live(dirs, monkeypatch):
    use_planner(monkeypatch, FakePlanner())
    response = start()
    assert response.status_code == 202
    run_id = response.json()["id"]
    wait_until_idle()
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["status"] == "finished" and body["is_replay"] is False and body["budget"] == 8
    assert body["total"] == 8
    assert {e["source"] for e in body["entries"]} == {"model", "optimizer"}
    assert client.get(f"/api/runs/{run_id}/entries/0/audio").status_code == 200
    assert run_id in {run["id"] for run in client.get("/api/runs").json()}
    assert (dirs / "live" / f"{run_id}.jsonl").exists()
    assert list((dirs / "runs").iterdir()) == []


def test_entries_appear_while_the_run_is_going(dirs, monkeypatch):
    import threading

    release = threading.Event()
    use_planner(monkeypatch, FakePlanner(release))
    run_id = start().json()["id"]
    during = client.get(f"/api/runs/{run_id}").json()
    assert during["status"] == "running" and during["is_replay"] is False and during["total"] == 0
    release.set()
    deadline = time.monotonic() + 30
    while client.get(f"/api/runs/{run_id}").json()["total"] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client.get(f"/api/runs/{run_id}?after=-1&limit=1").json()["entries"]
    wait_until_idle()


def test_run_can_be_polled_as_soon_as_it_is_started(dirs, monkeypatch):
    import threading

    release = threading.Event()
    use_planner(monkeypatch, FakePlanner(release))
    run_id = start().json()["id"]
    assert client.get(f"/api/runs/{run_id}").status_code == 200
    release.set()


def test_finished_status_always_comes_with_every_entry(dirs, monkeypatch):
    use_planner(monkeypatch, FakePlanner())
    run_id = start().json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] == "finished":
            assert body["total"] == 8
            return
    raise AssertionError("run did not finish")


def test_only_one_live_run_at_a_time(dirs, monkeypatch):
    import threading

    release = threading.Event()
    use_planner(monkeypatch, FakePlanner(release))
    assert start().status_code == 202
    second = start()
    release.set()
    assert second.status_code == 409


def test_missing_key_gives_an_actionable_error_and_starts_nothing(dirs, monkeypatch):
    def no_key(root):
        raise SystemExit("No API key.")

    monkeypatch.setattr(api, "planner_from_env", no_key)
    response = start()
    assert response.status_code == 503 and "META_API_KEY" in response.text
    assert api._LIVE_RUNS == {}


def test_optimizer_only_needs_no_key(dirs, monkeypatch):
    def forbidden(root):
        raise AssertionError("no planner for optimizer_only")

    monkeypatch.setattr(api, "planner_from_env", forbidden)
    run_id = start(mode="optimizer_only").json()["id"]
    wait_until_idle()
    assert {e["source"] for e in client.get(f"/api/runs/{run_id}").json()["entries"]} == {"optimizer"}


def test_crash_is_reported_without_details(dirs, monkeypatch):
    class Broken:
        can_call = True

        def plan(self, context):
            raise RuntimeError("secret-looking detail")

    use_planner(monkeypatch, Broken())
    run_id = start().json()["id"]
    wait_until_idle()
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["status"] == "failed" and body["error"] == "RuntimeError"
    assert "secret-looking" not in str(body)


@pytest.mark.parametrize(
    "body, status",
    [
        ({"mode": "magic"}, 422),
        ({"budget": 0}, 422),
        ({"budget": 1000}, 422),
        ({"target": "../../etc/passwd"}, 404),
        ({"target": "nope"}, 404),
        ({"target": "upload_000000000000"}, 404),
    ],
)
def test_bad_requests_are_refused(dirs, monkeypatch, body, status):
    use_planner(monkeypatch, FakePlanner())
    assert start(**body).status_code == status
    assert api._LIVE_RUNS == {}


def test_sound_with_no_pitch_is_refused(dirs, monkeypatch):
    use_planner(monkeypatch, FakePlanner())
    monkeypatch.setattr(api, "extract", lambda audio, estimate_pitch=False: type("F", (), {"f0_hz": None})())
    assert "no_pitch" in start().text


def wav_upload():
    buffer = io.BytesIO()
    soundfile.write(buffer, 0.5 * oscillator("saw", 220.0, SAMPLE_RATE * 2), SAMPLE_RATE, format="WAV")
    return {"file": ("mine.wav", buffer.getvalue(), "audio/wav")}


def test_upload_can_be_played_and_reconstructed(dirs, monkeypatch):
    use_planner(monkeypatch, FakePlanner())
    upload = client.post("/api/analyze", files=wav_upload()).json()
    upload_id = upload["upload_id"]
    assert upload_id.startswith("upload_")
    assert client.get(f"/api/targets/{upload_id}/audio").status_code == 200
    run_id = start(target=upload_id).json()["id"]
    wait_until_idle()
    assert client.get(f"/api/runs/{run_id}").json()["target"] == upload_id
    edit = client.post("/api/render", json={"recipe": RECIPE, "target": upload_id}).json()
    assert edit["loss"] is not None


def test_rejected_upload_stores_nothing(dirs):
    response = client.post("/api/analyze", files={"file": ("bad.txt", b"nope", "text/plain")})
    assert response.status_code >= 400 and not (dirs / "live" / "uploads").exists()


def test_alchemy_returns_playable_measured_variants(dirs):
    body = client.post("/api/alchemy", json={"recipe": RECIPE, "prompt": "brighter and more atmospheric, keep the pitch"}).json()
    assert len(body["variants"]) == 3
    for variant in body["variants"]:
        audio, rate = soundfile.read(io.BytesIO(base64.b64decode(variant["audio"].split(",")[1])))
        assert rate == SAMPLE_RATE and np.max(np.abs(audio)) > 0
        assert variant["spectrogram"].startswith("data:image/png") and variant["pitch_preserved"]


@pytest.mark.parametrize("prompt, message", [("more metallic", "can't do this yet"), ("nicer", "Say what should change")])
def test_alchemy_refuses_what_it_cannot_do(dirs, prompt, message):
    response = client.post("/api/alchemy", json={"recipe": RECIPE, "prompt": prompt})
    assert response.status_code == 422 and message in response.text


def test_alchemy_refuses_a_bad_recipe(dirs):
    response = client.post("/api/alchemy", json={"recipe": {"oscillator": {}}, "prompt": "brighter"})
    assert response.status_code == 422 and "isn't valid" in response.text
