"""Confirm Meta Model API access: one structured-output call with the planner schema.

Sends a spectrogram PNG of a self-generated test tone, plus its descriptors, and
checks the reply against the planner schema and parameter bounds.

    python scripts/check_api.py             # makes one billed API call
    python scripts/check_api.py --dry-run   # prints the request, sends nothing
    python scripts/check_api.py --no-image  # text only, if vision input is the problem
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import librosa
import numpy as np
from dotenv import load_dotenv
from PIL import Image
from scipy import signal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.schema import BOUNDS, PLANNER_OUTPUT_SCHEMA, validate_planner_output  # noqa: E402

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
SAMPLE_RATE = 44100
TEST_PITCH_HZ = 220.0


def make_test_tone() -> np.ndarray:
    """A 2 s decaying, low-passed 220 Hz saw. Deterministic and self-generated."""
    t = np.arange(int(2.0 * SAMPLE_RATE)) / SAMPLE_RATE
    saw = signal.sawtooth(2 * np.pi * TEST_PITCH_HZ * t)
    sos = signal.butter(2, 2800, "lowpass", fs=SAMPLE_RATE, output="sos")
    tone = signal.sosfilt(sos, saw) * np.exp(-1.5 * t)
    return tone / np.max(np.abs(tone))


def describe(audio: np.ndarray) -> dict[str, float]:
    # Pitch is measured here, never guessed by the model (locked decision 5).
    f0, _, _ = librosa.pyin(audio, fmin=65, fmax=2000, sr=SAMPLE_RATE)
    centroid = librosa.feature.spectral_centroid(y=audio, sr=SAMPLE_RATE)
    flatness = librosa.feature.spectral_flatness(y=audio)
    return {
        "duration_s": round(len(audio) / SAMPLE_RATE, 3),
        "f0_hz": round(float(np.nanmedian(f0)), 2),
        "spectral_centroid_hz": round(float(np.mean(centroid)), 1),
        "spectral_flatness": round(float(np.mean(flatness)), 5),
    }


def spectrogram_png(audio: np.ndarray) -> bytes:
    """Log-magnitude spectrogram as a grayscale PNG, low frequencies at the bottom."""
    db = librosa.amplitude_to_db(np.abs(librosa.stft(audio, n_fft=2048)), ref=np.max)
    pixels = ((db + 80).clip(0, 80) / 80 * 255).astype(np.uint8)[::-1]
    buffer = io.BytesIO()
    Image.fromarray(pixels).resize((512, 512)).save(buffer, format="PNG")
    return buffer.getvalue()


def build_payload(model: str, descriptors: dict[str, float], png: bytes | None) -> dict[str, Any]:
    text = (
        "Target sound descriptors:\n"
        f"{json.dumps(descriptors)}\n\n"
        "Allowed nodes: oscillator (required), oscillator_2, envelope (required), "
        "filter, distortion, delay. Return null for a node you want switched off.\n"
        f"Parameter bounds, as [min, max]: {json.dumps(BOUNDS)}\n"
        "Pitch is already fixed from the f0 estimate, so do not propose it.\n"
        "Best recipe so far: none. Recent experiments: none. Remaining render budget: 20.\n"
        "Propose the first structural hypothesis."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if png is not None:
        encoded = base64.b64encode(png).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
        )
    return {
        "model": model,
        "messages": [
            {
                "role": "developer",
                "content": (
                    "You plan experiments that reconstruct a sound with a small synthesizer. "
                    "You choose the structure and rough parameter regions; a numeric optimizer "
                    "fine-tunes the values later. Stay inside the given bounds."
                ),
            },
            {"role": "user", "content": content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "planner_output",
                "strict": True,
                "schema": PLANNER_OUTPUT_SCHEMA,
            },
        },
    }


def redacted(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with image bytes shortened, for printing."""
    copy = json.loads(json.dumps(payload))
    for part in copy["messages"][1]["content"]:
        if part["type"] == "image_url":
            size = len(part["image_url"]["url"])
            part["image_url"]["url"] = f"data:image/png;base64,<{size} chars>"
    return copy


def run_check(
    payload: dict[str, Any], api_key: str, transport: httpx.BaseTransport | None = None
) -> int:
    """Make the call, report what came back, and return a process exit code."""
    started = time.monotonic()
    with httpx.Client(base_url=BASE_URL, timeout=180, transport=transport) as client:
        try:
            response = client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        except httpx.HTTPError as error:
            print(f"FAILED: request error: {error!r}")
            return 1
    elapsed = time.monotonic() - started

    print(f"HTTP {response.status_code} in {elapsed:.1f}s, model requested: {payload['model']}")
    if response.status_code != 200:
        print(f"FAILED: {response.text[:2000]}")
        return 1

    try:
        body = response.json()
        choice = body["choices"][0]
        raw = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        print(f"FAILED: unexpected response shape ({error!r}): {response.text[:2000]}")
        return 1

    print(f"Model reported: {body.get('model')}, finish_reason: {choice.get('finish_reason')}")
    print(f"Usage: {json.dumps(body.get('usage'))}")
    print(f"Raw content:\n{raw}\n")

    try:
        output = json.loads(raw)
    except (TypeError, ValueError) as error:
        print(f"FAILED: content is not JSON: {error}")
        return 1

    errors = validate_planner_output(output)
    if errors:
        print("FAILED: response rejected by local validation:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("PASSED: valid structured response (planner schema and parameter bounds).")
    print(json.dumps(output, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    parser.add_argument("--no-image", action="store_true", help="leave out the spectrogram")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model = os.environ.get("META_MODEL") or DEFAULT_MODEL
    # Meta's docs call this MODEL_API_KEY; this project's .env calls it META_API_KEY.
    api_key = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")

    audio = make_test_tone()
    descriptors = describe(audio)
    png = None if args.no_image else spectrogram_png(audio)
    payload = build_payload(model, descriptors, png)

    if args.dry_run:
        print(json.dumps(redacted(payload), indent=2))
        print(f"\nDry run: nothing sent. Spectrogram PNG: {len(png) if png else 0} bytes.")
        return 0

    if not api_key:
        print("FAILED: no API key. Set META_API_KEY in .env (from https://dev.meta.ai/api-keys/).")
        return 2

    return run_check(payload, api_key)


if __name__ == "__main__":
    sys.exit(main())
