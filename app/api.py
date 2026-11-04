"""Thin HTTP layer for the Next.js frontend. No DSP or scoring logic lives here.

    .venv/bin/uvicorn app.api:app --port 8000

Replays read logged runs and make no model calls. The log's `score` field is dropped on
purpose so the UI cannot show it. Runs and targets are looked up by validated name only.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import soundfile
from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

from app.dsp import render as render_recipe
from app.features import Features, extract, preprocess, spectrogram_png
from app.loss import WEIGHTS, compare
from app.schema import RECIPE_BOUNDS, SAMPLE_RATE, validate_recipe

ROOT = Path(__file__).resolve().parent.parent

# Below the 10 MB body limit of the Next.js proxy, which stalls on anything larger.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MIN_DURATION_S = 1.0
MAX_DURATION_S = 5.0
MAX_CHANNELS = 2
MIN_SOUNDING_S = 0.5
CLIP_LEVEL = 0.999
MAX_CLIPPED_FRACTION = 0.001
SILENCE_PEAK = 1e-3
WAVEFORM_POINTS = 480

_NAME = re.compile(r"[A-Za-z0-9_]+")
_RUN_ID = re.compile(r"(?P<target>[A-Za-z0-9_]+)-(?P<mode>[A-Za-z0-9_]+)-seed(?P<seed>\d+)")
_ENTRY_FIELDS = (
    "timestamp",
    "seed",
    "planner_call",
    "hypothesis",
    "rationale",
    "expected_effect",
    "recipe",
    "loss",
    "components",
    "failure",
    "best_loss",
)

app = FastAPI(title="SonicDNA API")


def _runs_dir() -> Path:
    return Path(os.environ.get("SONICDNA_RUNS_DIR") or ROOT / "runs")


def _targets_dir() -> Path:
    return Path(os.environ.get("SONICDNA_TARGETS_DIR") or ROOT / "data" / "targets")


def _error(status: int, code: str, message: str, fix: str | None = None) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, "fix": fix})


# ---------------------------------------------------------------- targets


def _manifest() -> dict[str, Any]:
    path = _targets_dir() / "manifest.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _target_wav(name: str) -> Path:
    """The WAV for a target listed in the manifest. 404 for any other name."""
    if not _NAME.fullmatch(name) or name not in _manifest():
        raise _error(404, "unknown_target", f"There is no target called '{name}'.")
    path = _targets_dir() / f"{name}.wav"
    if not path.is_file():
        raise _error(
            404,
            "target_audio_missing",
            f"The audio for target '{name}' is missing.",
            "Run: python scripts/make_targets.py",
        )
    return path


def _is_held_out(name: str) -> bool:
    return _manifest().get(name, {}).get("split") == "held_out"


def _has_logged_run(target: str) -> bool:
    return any(run["target"] == target for run in _list_runs())


def _wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    soundfile.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@lru_cache(maxsize=32)
def _reference_cached(path: str, modified: float) -> tuple[np.ndarray, Features]:
    audio, sample_rate = soundfile.read(path)
    processed = preprocess(audio, sample_rate)
    return processed, extract(processed)


def _reference(name: str) -> tuple[np.ndarray, Features]:
    path = _target_wav(name)
    return _reference_cached(str(path), path.stat().st_mtime)


def _waveform(audio: np.ndarray) -> dict[str, list[float]]:
    """Min and max per display column, for drawing only."""
    points = min(WAVEFORM_POINTS, max(1, len(audio)))
    columns = np.array_split(audio, points)
    return {
        "min": [round(float(c.min()), 4) for c in columns],
        "max": [round(float(c.max()), 4) for c in columns],
    }


def _data_url(media_type: str, payload: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(payload).decode()}"


def _analysis(audio: np.ndarray) -> dict[str, Any]:
    return {
        "descriptors": extract(audio, estimate_pitch=True).descriptors(),
        "waveform": _waveform(audio),
        "spectrogram": _data_url("image/png", spectrogram_png(audio)),
    }


# ---------------------------------------------------------------- run logs


def _finite(value: Any) -> Any:
    """Replace NaN and infinity, which json.loads accepts but JSON responses can't carry."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite(item) for item in value]
    return value


def _normalize_entry(raw: dict[str, Any], position: int, run_mode: str) -> dict[str, Any]:
    """Every known field present, absent ones null. Unknown fields, and score, are dropped."""
    entry = {field: _finite(raw.get(field)) for field in _ENTRY_FIELDS}
    index = raw.get("index")
    entry["index"] = index if isinstance(index, int) else position
    entry["mode"] = raw.get("mode") or run_mode
    entry["source"] = raw.get("source")
    entry["is_best"] = bool(raw.get("is_best"))
    return entry


def _run_path(run_id: str) -> tuple[Path, re.Match[str]]:
    match = _RUN_ID.fullmatch(run_id)
    if match is None:
        raise _error(404, "unknown_run", "There is no logged run with that name.")
    runs_dir = _runs_dir().resolve()
    path = (runs_dir / f"{run_id}.jsonl").resolve()
    if not path.is_relative_to(runs_dir) or not path.is_file():
        raise _error(404, "unknown_run", "There is no logged run with that name.")
    return path, match


def _read_run(path: Path, mode: str) -> tuple[list[dict[str, Any]], int]:
    """Entries in the log, plus how many lines couldn't be read (say, a half-written one)."""
    entries: list[dict[str, Any]] = []
    skipped = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(raw, dict):
            skipped += 1
            continue
        entries.append(_normalize_entry(raw, len(entries) + skipped, mode))
    return entries, skipped


def _list_runs() -> list[dict[str, Any]]:
    runs_dir = _runs_dir()
    if not runs_dir.is_dir():
        return []
    runs = []
    for path in sorted(runs_dir.glob("*.jsonl")):
        match = _RUN_ID.fullmatch(path.stem)
        if match is None:
            continue
        entries, skipped = _read_run(path, match["mode"])
        losses = [e["loss"] for e in entries if isinstance(e["loss"], (int, float))]
        runs.append(
            {
                "id": path.stem,
                "target": match["target"],
                "mode": match["mode"],
                "seed": int(match["seed"]),
                "entries": len(entries),
                "skipped_lines": skipped,
                "best_loss": min(losses) if losses else None,
            }
        )
    return runs


def _entry(run_id: str, index: int) -> dict[str, Any]:
    path, match = _run_path(run_id)
    entries, _ = _read_run(path, match["mode"])
    for entry in entries:
        if entry["index"] == index:
            return entry
    raise _error(404, "unknown_entry", f"Run '{run_id}' has no entry {index}.")


def _render_entry(run_id: str, index: int) -> np.ndarray:
    entry = _entry(run_id, index)
    try:
        return render_recipe(entry["recipe"])
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise _error(
            422,
            "unrenderable_entry",
            f"Entry {index} has no recipe that can be rendered: {error}",
            "Pick another step.",
        ) from error


# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {
        "loss_weights": WEIGHTS,
        "recipe_bounds": {path: list(bound) for path, bound in RECIPE_BOUNDS.items()},
        "upload_limits": {
            "max_bytes": MAX_UPLOAD_BYTES,
            "min_duration_s": MIN_DURATION_S,
            "max_duration_s": MAX_DURATION_S,
            "max_channels": MAX_CHANNELS,
        },
    }


@app.get("/api/targets")
def targets() -> list[dict[str, Any]]:
    """Names and split only. Ground-truth recipes stay out of the UI."""
    logged = {run["target"] for run in _list_runs()}
    return [
        {
            "name": name,
            "held_out": entry.get("split") == "held_out",
            "available": (_targets_dir() / f"{name}.wav").is_file(),
            "has_runs": name in logged,
        }
        for name, entry in _manifest().items()
    ]


@app.get("/api/targets/{name}/audio")
def target_audio(name: str) -> Response:
    audio, sample_rate = soundfile.read(_target_wav(name))
    return Response(_wav_bytes(audio, sample_rate), media_type="audio/wav")


@app.get("/api/targets/{name}/analysis")
def target_analysis(name: str) -> dict[str, Any]:
    _target_wav(name)
    if _is_held_out(name):
        raise _error(
            403,
            "held_out",
            f"'{name}' is held out for the final evaluation. You can play it, but it isn't analysed.",
            "Pick a development target or upload a WAV.",
        )
    return {"name": name, "warnings": [], **_analysis(_reference(name)[0])}


@app.get("/api/targets/{name}/spectrogram")
def target_spectrogram(name: str) -> Response:
    _target_wav(name)
    # A held-out target's picture only appears once a final-evaluation run has been logged.
    if _is_held_out(name) and not _has_logged_run(name):
        raise _error(403, "held_out", f"'{name}' is held out for the final evaluation.")
    return Response(spectrogram_png(_reference(name)[0]), media_type="image/png")


@app.post("/api/analyze")
def analyze_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Validate an uploaded WAV and analyse it. Runs locally; nothing is stored or sent on."""
    payload = file.file.read(MAX_UPLOAD_BYTES + 1)
    audio, sample_rate, warnings = _validate_upload(file.filename or "", payload)
    processed = preprocess(audio, sample_rate)
    sounding = len(processed) / SAMPLE_RATE
    if sounding < MIN_SOUNDING_S:
        raise _error(
            422,
            "too_short_after_trim",
            f"Only {sounding:.2f} s remains once leading silence is removed.",
            f"Use a sound with at least {MIN_SOUNDING_S} s of audio after it starts.",
        )
    return {"name": file.filename, "warnings": warnings, **_analysis(processed)}


def _validate_upload(filename: str, payload: bytes) -> tuple[np.ndarray, int, list[str]]:
    if len(payload) > MAX_UPLOAD_BYTES:
        raise _error(
            413,
            "file_too_large",
            f"That file is over the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            f"Trim it to {MAX_DURATION_S:.0f} seconds or less and export again.",
        )
    wav_fix = "Export the sound as a .wav file and upload that."
    if not filename.lower().endswith((".wav", ".wave")):
        raise _error(415, "wrong_type", "Only WAV files are supported.", wav_fix)
    if not payload:
        raise _error(422, "empty_file", "That file is empty.", wav_fix)
    try:
        with soundfile.SoundFile(io.BytesIO(payload)) as handle:
            container, channels = handle.format, handle.channels
            sample_rate, frames = handle.samplerate, handle.frames
            if container not in {"WAV", "WAVEX", "RF64"}:
                raise _error(
                    415, "wrong_type", f"That file is {container}, not WAV, inside.", wav_fix
                )
            if channels > MAX_CHANNELS:
                raise _error(
                    422,
                    "too_many_channels",
                    f"That file has {channels} channels. SonicDNA accepts mono or stereo.",
                    "Mix it down to mono and export again.",
                )
            duration = frames / sample_rate
            if duration < MIN_DURATION_S or duration > MAX_DURATION_S:
                raise _error(
                    422,
                    "bad_duration",
                    f"That sound is {duration:.2f} s long. It must be "
                    f"{MIN_DURATION_S:.0f} to {MAX_DURATION_S:.0f} seconds.",
                    "Trim it to one isolated sound of 1 to 5 seconds.",
                )
            audio = handle.read(dtype="float64")
    except soundfile.LibsndfileError as error:
        raise _error(
            415, "unreadable_audio", "That file can't be read as WAV audio.", wav_fix
        ) from error

    if not np.isfinite(audio).all():
        raise _error(
            422,
            "bad_samples",
            "That file contains invalid sample values.",
            "Export it again as 16-bit PCM WAV.",
        )
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < SILENCE_PEAK:
        raise _error(
            422,
            "silent",
            "That file is silent or almost silent.",
            "Check the recording level and export again.",
        )
    clipped = float(np.mean(np.abs(audio) >= CLIP_LEVEL))
    if clipped > MAX_CLIPPED_FRACTION:
        raise _error(
            422,
            "clipped",
            "That sound is clipped: its loudest parts hit the digital ceiling, which adds distortion.",
            "Lower the level by 3 to 6 dB and export again.",
        )
    warnings = []
    if channels == 2:
        warnings.append("Stereo file: mixed down to mono for analysis.")
    if sample_rate != SAMPLE_RATE:
        warnings.append(f"Resampled from {sample_rate} Hz to {SAMPLE_RATE} Hz for analysis.")
    return audio, sample_rate, warnings


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    return _list_runs()


@app.get("/api/runs/{run_id}")
def run_entries(
    run_id: str,
    after: int = Query(-1, description="Return entries after this position in the log."),
    limit: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    """A logged run, for replay. The client paces the reveal; this only reads the log."""
    path, match = _run_path(run_id)
    entries, skipped = _read_run(path, match["mode"])
    start = max(after + 1, 0)
    stop = None if limit is None else start + limit
    return {
        "id": run_id,
        "target": match["target"],
        "mode": match["mode"],
        "seed": int(match["seed"]),
        "is_replay": True,
        "total": len(entries),
        "skipped_lines": skipped,
        "entries": entries[start:stop],
    }


@app.get("/api/runs/{run_id}/entries/{index}/audio")
def entry_audio(run_id: str, index: int) -> Response:
    return Response(_wav_bytes(_render_entry(run_id, index)), media_type="audio/wav")


@app.get("/api/runs/{run_id}/entries/{index}/spectrogram")
def entry_spectrogram(run_id: str, index: int) -> Response:
    return Response(spectrogram_png(_render_entry(run_id, index)), media_type="image/png")


class RenderRequest(BaseModel):
    recipe: dict[str, Any]
    target: str | None = None


@app.post("/api/render")
def render_edit(request: RenderRequest) -> dict[str, Any]:
    """Render a manually edited recipe. It is never written to any experiment log."""
    errors = validate_recipe(request.recipe)
    if errors:
        raise _error(422, "invalid_recipe", "; ".join(errors), "Keep values inside their bounds.")
    audio = render_recipe(request.recipe)
    result: dict[str, Any] = {
        "audio": _data_url("audio/wav", _wav_bytes(audio)),
        "spectrogram": _data_url("image/png", spectrogram_png(audio)),
        "loss": None,
        "components": None,
        "not_scored_reason": None,
    }
    if request.target is None:
        result["not_scored_reason"] = "No reference was given."
    elif _is_held_out(request.target):
        _target_wav(request.target)
        result["not_scored_reason"] = "Manual edits aren't scored against held-out targets."
    else:
        comparison = compare(_reference(request.target)[1], extract(audio))
        result["loss"] = comparison.loss
        result["components"] = comparison.components
    return result
