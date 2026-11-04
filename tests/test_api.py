"""HTTP layer: upload validation, listings, replay, log-format tolerance, path safety.

Everything runs against temporary directories, so runs/ and data/ are never touched.
"""

import io
import json

import numpy as np
import pytest
import soundfile
from fastapi.testclient import TestClient

from app.api import MAX_UPLOAD_BYTES, app
from app.dsp import render
from app.features import extract, preprocess
from app.loss import compare
from app.schema import SAMPLE_RATE

client = TestClient(app)


def recipe(**overrides):
    return {
        "schema_version": "1.0",
        "sample_rate": SAMPLE_RATE,
        "duration_s": 1.0,
        "oscillator": {"type": "saw", "frequency_hz": 220.0, "gain": 0.7},
        "oscillator_2": None,
        "envelope": {"attack_s": 0.02, "decay_s": 0.2, "sustain": 0.5, "release_s": 0.2},
        "filter": {"type": "lowpass", "cutoff_hz": 2000.0},
        "distortion": None,
        "delay": None,
        **overrides,
    }


def today_entry(index=0, loss=0.5, **overrides):
    """Exactly the fields today's logs have."""
    return {
        "index": index,
        "timestamp": "2026-11-04T15:46:37+00:00",
        "mode": "random",
        "seed": 0,
        "source": "random",
        "recipe": recipe(),
        "loss": loss,
        "components": {"stft": 0.1, "centroid": 0.2, "envelope": 0.3},
        "score": 0.1234,
        "failure": None,
        "is_best": True,
        "best_loss": loss,
        **overrides,
    }


def write_run(runs_dir, name, entries):
    (runs_dir / f"{name}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    runs_dir = tmp_path / "logs"
    targets_dir = tmp_path / "targets"
    monkeypatch.setenv("SONICDNA_LIVE_DIR", str(tmp_path / "live"))
    runs_dir.mkdir()
    targets_dir.mkdir()
    audio = render(recipe())
    for name in ("tone", "secret"):
        soundfile.write(targets_dir / f"{name}.wav", audio, SAMPLE_RATE, subtype="FLOAT")
    manifest = {
        "tone": {"split": "dev", "recipe": recipe()},
        "secret": {"split": "held_out", "recipe": recipe()},
        "gone": {"split": "dev", "recipe": recipe()},
    }
    (targets_dir / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("SONICDNA_RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("SONICDNA_TARGETS_DIR", str(targets_dir))
    write_run(runs_dir, "tone-random-seed0", [today_entry(0, 0.5), today_entry(1, 0.4)])
    return runs_dir, targets_dir


def wav_upload(audio, sample_rate=SAMPLE_RATE, name="sound.wav", subtype="PCM_16"):
    buffer = io.BytesIO()
    soundfile.write(buffer, audio, sample_rate, format="WAV", subtype=subtype)
    return {"file": (name, buffer.getvalue(), "audio/wav")}


def tone(seconds=1.5, level=0.3, sample_rate=SAMPLE_RATE):
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return level * np.sin(2 * np.pi * 220 * t)


def error_code(response):
    return response.json()["detail"]["code"]


# ------------------------------------------------------------ upload validation


def test_upload_valid_returns_analysis():
    response = client.post("/api/analyze", files=wav_upload(tone()))
    assert response.status_code == 200
    body = response.json()
    assert body["descriptors"]["f0_hz"] == pytest.approx(220, rel=0.02)
    assert body["spectrogram"].startswith("data:image/png;base64,")
    assert len(body["waveform"]["min"]) == len(body["waveform"]["max"]) > 0
    assert body["warnings"] == []


@pytest.mark.parametrize(
    "files, status, code",
    [
        ({"file": ("sound.mp3", b"ID3xxxx", "audio/mpeg")}, 415, "wrong_type"),
        ({"file": ("fake.wav", b"this is not audio", "audio/wav")}, 415, "unreadable_audio"),
        ({"file": ("empty.wav", b"", "audio/wav")}, 422, "empty_file"),
        ({"file": ("huge.wav", b"\0" * (MAX_UPLOAD_BYTES + 1), "audio/wav")}, 413, "file_too_large"),
    ],
)
def test_upload_rejects_bad_files(files, status, code):
    response = client.post("/api/analyze", files=files)
    assert response.status_code == status
    assert error_code(response) == code
    assert response.json()["detail"]["fix"]


def test_upload_rejects_flac_renamed_to_wav():
    buffer = io.BytesIO()
    soundfile.write(buffer, tone(), SAMPLE_RATE, format="FLAC")
    response = client.post("/api/analyze", files={"file": ("x.wav", buffer.getvalue(), "audio/wav")})
    assert response.status_code == 415
    assert error_code(response) == "wrong_type"


@pytest.mark.parametrize("seconds", [0.5, 5.5])
def test_upload_rejects_bad_duration(seconds):
    response = client.post("/api/analyze", files=wav_upload(tone(seconds)))
    assert response.status_code == 422
    assert error_code(response) == "bad_duration"


def test_upload_rejects_too_many_channels():
    audio = np.stack([tone()] * 3, axis=1)
    response = client.post("/api/analyze", files=wav_upload(audio))
    assert response.status_code == 422
    assert error_code(response) == "too_many_channels"


def test_upload_rejects_clipping():
    response = client.post("/api/analyze", files=wav_upload(np.clip(tone(level=3.0), -1, 1)))
    assert response.status_code == 422
    assert error_code(response) == "clipped"


def test_upload_rejects_silence():
    response = client.post("/api/analyze", files=wav_upload(np.zeros(SAMPLE_RATE * 2)))
    assert response.status_code == 422
    assert error_code(response) == "silent"


def test_upload_rejects_too_little_sound_after_trim():
    audio = np.concatenate([np.zeros(int(SAMPLE_RATE * 1.4)), tone(0.1)])
    response = client.post("/api/analyze", files=wav_upload(audio))
    assert response.status_code == 422
    assert error_code(response) == "too_short_after_trim"


def test_upload_rejects_non_finite_samples():
    audio = tone()
    audio[100] = np.nan
    response = client.post("/api/analyze", files=wav_upload(audio, subtype="FLOAT"))
    assert response.status_code == 422
    assert error_code(response) == "bad_samples"


def test_upload_stereo_and_other_rate_are_accepted_with_warnings():
    audio = np.stack([tone(sample_rate=22050)] * 2, axis=1)
    response = client.post("/api/analyze", files=wav_upload(audio, sample_rate=22050))
    assert response.status_code == 200
    warnings = " ".join(response.json()["warnings"])
    assert "Stereo" in warnings and "22050" in warnings


# ------------------------------------------------------------ targets


def test_target_listing_hides_ground_truth_and_flags_state(dirs):
    listed = {t["name"]: t for t in client.get("/api/targets").json()}
    assert listed["tone"] == {
        "name": "tone",
        "held_out": False,
        "available": True,
        "has_runs": True,
    }
    assert listed["secret"]["held_out"] is True
    assert listed["gone"]["available"] is False
    assert "recipe" not in json.dumps(listed)


def test_target_audio_and_analysis(dirs):
    audio = client.get("/api/targets/tone/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert client.get("/api/targets/tone/analysis").json()["descriptors"]["f0_hz"] > 0
    assert client.get("/api/targets/tone/spectrogram").headers["content-type"] == "image/png"


def test_missing_target_audio_says_how_to_fix_it(dirs):
    response = client.get("/api/targets/gone/audio")
    assert response.status_code == 404
    assert "make_targets" in response.json()["detail"]["fix"]


def test_held_out_targets_are_open_now_the_evaluation_is_finished(dirs):
    assert client.get("/api/targets/secret/analysis").status_code == 200
    assert client.get("/api/targets/secret/spectrogram").status_code == 200
    body = client.post("/api/render", json={"recipe": recipe(), "target": "secret"}).json()
    assert body["loss"] is not None and body["not_scored_reason"] is None


def test_run_listing(dirs):
    write_run(dirs[0], "tone-optimizer_only-seed3", [today_entry(0, 0.2)])
    (dirs[0] / "notes.jsonl").write_text("not a run\n")
    listed = {r["id"]: r for r in client.get("/api/runs").json()}
    assert set(listed) == {"tone-random-seed0", "tone-optimizer_only-seed3"}
    assert listed["tone-optimizer_only-seed3"]["mode"] == "optimizer_only"
    assert listed["tone-optimizer_only-seed3"]["seed"] == 3
    assert listed["tone-random-seed0"]["best_loss"] == 0.4
    assert listed["tone-random-seed0"]["entries"] == 2


def test_missing_runs_dir_lists_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SONICDNA_RUNS_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("SONICDNA_LIVE_DIR", str(tmp_path / "nowhere-live"))
    assert client.get("/api/runs").json() == []


def test_runs_dir_env_override_is_honoured(tmp_path, monkeypatch, dirs):
    other = tmp_path / "deployed"
    other.mkdir()
    write_run(other, "tone-hybrid-seed9", [today_entry()])
    monkeypatch.setenv("SONICDNA_RUNS_DIR", str(other))
    assert [r["id"] for r in client.get("/api/runs").json()] == ["tone-hybrid-seed9"]


def test_replay_is_labelled_and_in_log_order(dirs):
    body = client.get("/api/runs/tone-random-seed0").json()
    assert body["is_replay"] is True
    assert body["total"] == 2
    assert [e["index"] for e in body["entries"]] == [0, 1]


def test_replay_can_be_read_step_by_step(dirs):
    first = client.get("/api/runs/tone-random-seed0", params={"limit": 1}).json()
    second = client.get("/api/runs/tone-random-seed0", params={"after": 0, "limit": 1}).json()
    done = client.get("/api/runs/tone-random-seed0", params={"after": 1}).json()
    assert [e["index"] for e in first["entries"]] == [0]
    assert [e["index"] for e in second["entries"]] == [1]
    assert done["entries"] == [] and done["total"] == 2


def test_todays_entries_get_null_new_fields_and_lose_score(dirs):
    entry = client.get("/api/runs/tone-random-seed0").json()["entries"][0]
    assert entry["source"] == "random"
    assert entry["planner_call"] is None
    assert entry["hypothesis"] is None
    assert entry["rationale"] is None
    assert entry["expected_effect"] is None
    assert "score" not in entry


def test_new_fields_pass_through_unchanged(dirs):
    write_run(
        dirs[0],
        "tone-hybrid-seed0",
        [
            today_entry(
                mode="hybrid",
                source="model",
                planner_call=2,
                hypothesis="h text",
                rationale="r text",
                expected_effect="e text",
            )
        ],
    )
    entry = client.get("/api/runs/tone-hybrid-seed0").json()["entries"][0]
    assert entry["mode"] == "hybrid"
    assert entry["source"] == "model"
    assert entry["planner_call"] == 2
    assert entry["hypothesis"] == "h text"
    assert entry["rationale"] == "r text"
    assert entry["expected_effect"] == "e text"


def test_unknown_fields_never_reach_the_ui(dirs):
    write_run(dirs[0], "tone-hybrid-seed1", [today_entry(api_key="nope", raw_prompt="nope")])
    assert "nope" not in client.get("/api/runs/tone-hybrid-seed1").text


def test_failed_entry_with_null_loss(dirs):
    write_run(
        dirs[0],
        "tone-hybrid-seed2",
        [
            today_entry(
                0,
                loss=None,
                components=None,
                score=None,
                failure="invalid recipe: filter.cutoff_hz=1 is outside [20.0, 20000.0]",
                is_best=False,
                best_loss=None,
                recipe={"oscillator": "broken"},
                source="model",
            )
        ],
    )
    entry = client.get("/api/runs/tone-hybrid-seed2").json()["entries"][0]
    assert entry["loss"] is None and entry["best_loss"] is None
    assert "outside" in entry["failure"]
    assert client.get("/api/runs").status_code == 200
    audio = client.get("/api/runs/tone-hybrid-seed2/entries/0/audio")
    assert audio.status_code == 422
    assert error_code(audio) == "unrenderable_entry"


def test_nan_in_a_log_becomes_null(dirs):
    path = dirs[0] / "tone-hybrid-seed4.jsonl"
    path.write_text(json.dumps(today_entry(loss=float("nan"))) + "\n")
    response = client.get("/api/runs/tone-hybrid-seed4")
    assert response.status_code == 200
    assert response.json()["entries"][0]["loss"] is None


def test_half_written_line_is_counted_not_fatal(dirs):
    path = dirs[0] / "tone-hybrid-seed5.jsonl"
    path.write_text(json.dumps(today_entry()) + '\n{"index": 1, "reci')
    body = client.get("/api/runs/tone-hybrid-seed5").json()
    assert body["total"] == 1 and body["skipped_lines"] == 1


def test_entry_render_is_deterministic_and_matches_dsp(dirs):
    first = client.get("/api/runs/tone-random-seed0/entries/1/audio")
    second = client.get("/api/runs/tone-random-seed0/entries/1/audio")
    assert first.status_code == 200 and first.content == second.content
    audio, sample_rate = soundfile.read(io.BytesIO(first.content))
    assert sample_rate == SAMPLE_RATE
    assert np.allclose(audio, render(recipe()), atol=1e-3)
    spectrogram = client.get("/api/runs/tone-random-seed0/entries/1/spectrogram")
    assert spectrogram.headers["content-type"] == "image/png"


def test_unknown_entry_is_404(dirs):
    assert client.get("/api/runs/tone-random-seed0/entries/99/audio").status_code == 404


# ------------------------------------------------------------ manual render


def test_manual_render_scores_with_the_same_code_as_the_search(dirs):
    edited = recipe(filter={"type": "lowpass", "cutoff_hz": 800.0})
    body = client.post("/api/render", json={"recipe": edited, "target": "tone"}).json()
    audio, sample_rate = soundfile.read(dirs[1] / "tone.wav")
    expected = compare(extract(preprocess(audio, sample_rate)), extract(render(edited)))
    assert body["loss"] == pytest.approx(expected.loss)
    assert body["components"] == pytest.approx(expected.components)
    assert "score" not in body
    assert body["audio"].startswith("data:audio/wav;base64,")


def test_manual_render_does_not_write_to_the_log(dirs):
    path = dirs[0] / "tone-random-seed0.jsonl"
    before = path.read_text()
    client.post("/api/render", json={"recipe": recipe(), "target": "tone"})
    assert path.read_text() == before


def test_manual_render_rejects_out_of_bounds(dirs):
    bad = recipe(filter={"type": "lowpass", "cutoff_hz": 5.0})
    response = client.post("/api/render", json={"recipe": bad, "target": "tone"})
    assert response.status_code == 422
    assert "cutoff_hz" in response.json()["detail"]["message"]


def test_manual_render_unknown_target_is_404(dirs):
    response = client.post("/api/render", json={"recipe": recipe(), "target": "../secret"})
    assert response.status_code == 404


def test_meta_exposes_bounds_and_no_score_field():
    body = client.get("/api/meta").json()
    assert body["recipe_bounds"]["filter.cutoff_hz"] == [20.0, 20000.0]
    assert "score" not in json.dumps(body)


# ------------------------------------------------------------ path traversal


@pytest.mark.parametrize(
    "name",
    [
        "..",
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..\\..\\secret",
        "/etc/passwd",
        "tone.wav",
        "manifest",
        "tone%00",
    ],
)
@pytest.mark.parametrize(
    "template",
    ["/api/targets/{}/audio", "/api/targets/{}/analysis", "/api/targets/{}/spectrogram"],
)
def test_target_name_traversal_is_refused(dirs, template, name):
    response = client.get(template.format(name))
    assert response.status_code in {404, 405}
    assert b"root:" not in response.content


@pytest.mark.parametrize(
    "name",
    [
        "..",
        "../../etc/passwd",
        "..%2Fsecret-hybrid-seed0",
        "%2e%2e%2fsecret-hybrid-seed0",
        "x%2F..%2Ftone-random-seed0",
        "tone-random-seed0.jsonl",
        "tone-random-seed0%00",
        "..-..-seed0",
    ],
)
@pytest.mark.parametrize(
    "template",
    ["/api/runs/{}", "/api/runs/{}/entries/0/audio", "/api/runs/{}/entries/0/spectrogram"],
)
def test_run_name_traversal_is_refused(tmp_path, dirs, template, name):
    # A real log just outside the runs directory, which a traversal would reach.
    write_run(dirs[0].parent, "secret-hybrid-seed0", [today_entry(hypothesis="leaked")])
    response = client.get(template.format(name))
    assert response.status_code in {404, 405}
    assert b"leaked" not in response.content


def test_symlink_out_of_the_runs_dir_is_refused(dirs):
    outside = dirs[0].parent / "outside.jsonl"
    outside.write_text(json.dumps(today_entry(hypothesis="leaked")) + "\n")
    (dirs[0] / "tone-hybrid-seed7.jsonl").symlink_to(outside)
    response = client.get("/api/runs/tone-hybrid-seed7")
    assert response.status_code == 404
