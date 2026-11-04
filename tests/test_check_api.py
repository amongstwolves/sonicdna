"""API check script, with the network faked. No key or billed call is involved."""

import base64
import json
from io import BytesIO

import httpx
import numpy as np
import pytest
from PIL import Image

from scripts.check_api import (
    SAMPLE_RATE,
    TEST_PITCH_HZ,
    build_payload,
    describe,
    make_test_tone,
    redacted,
    run_check,
    spectrogram_png,
)

VALID_OUTPUT = {
    "hypothesis": "A filtered saw.",
    "action": "propose_structure",
    "proposed_recipe_or_delta": {
        "oscillator": {"type": "saw", "gain": 0.7},
        "oscillator_2": None,
        "envelope": {"attack_s": 0.01, "decay_s": 0.5, "sustain": 0.2, "release_s": 0.3},
        "filter": {"type": "lowpass", "cutoff_hz": 2800},
        "distortion": None,
        "delay": None,
    },
    "expected_effect": "Matches the centroid.",
    "rationale": "Harmonics fall off.",
}


def completion(content):
    return {
        "model": "muse-spark-1.3",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"total_tokens": 10},
    }


def transport_returning(status, body):
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body))


@pytest.fixture
def payload():
    return build_payload("muse-spark-1.3", {"f0_hz": 220.0}, b"png-bytes")


def test_tone_is_deterministic_and_normalised():
    first, second = make_test_tone(), make_test_tone()
    assert np.array_equal(first, second)
    assert len(first) == 2 * SAMPLE_RATE
    assert np.max(np.abs(first)) == pytest.approx(1.0)


def test_descriptors_recover_the_test_pitch():
    descriptors = describe(make_test_tone())
    assert descriptors["f0_hz"] == pytest.approx(TEST_PITCH_HZ, abs=2.0)
    assert descriptors["duration_s"] == 2.0


def test_spectrogram_is_a_512px_grayscale_png_with_content():
    image = Image.open(BytesIO(spectrogram_png(make_test_tone())))
    assert image.format == "PNG" and image.size == (512, 512) and image.mode == "L"
    low, high = image.getextrema()
    assert high - low > 100


def test_spectrogram_has_low_frequencies_at_the_bottom():
    pixels = np.asarray(Image.open(BytesIO(spectrogram_png(make_test_tone()))))
    assert pixels[-128:].mean() > pixels[:128].mean()


def test_payload_puts_image_in_user_message_and_requests_strict_schema(payload):
    # Meta returns HTTP 400 for image content in developer or system messages.
    assert isinstance(payload["messages"][0]["content"], str)
    image_part = payload["messages"][1]["content"][1]
    assert image_part["type"] == "image_url"
    encoded = image_part["image_url"]["url"].removeprefix("data:image/png;base64,")
    assert base64.b64decode(encoded) == b"png-bytes"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_payload_without_image_is_text_only():
    payload = build_payload("m", {}, None)
    assert [part["type"] for part in payload["messages"][1]["content"]] == ["text"]


def test_redacted_hides_image_bytes_without_changing_the_payload(payload):
    original = json.dumps(payload)
    encoded = base64.b64encode(b"png-bytes").decode()
    assert encoded not in json.dumps(redacted(payload))
    assert json.dumps(payload) == original


def test_request_goes_to_chat_completions_with_bearer_auth(payload):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion(json.dumps(VALID_OUTPUT)))

    assert run_check(payload, "test-value", httpx.MockTransport(handler)) == 0
    assert seen["url"] == "https://api.meta.ai/v1/chat/completions"
    assert seen["auth"] == "Bearer test-value"
    assert seen["body"]["model"] == "muse-spark-1.3"


def test_key_is_never_printed(payload, capsys):
    run_check(payload, "test-value", transport_returning(401, {"error": "bad key"}))
    assert "test-value" not in capsys.readouterr().out


def test_valid_response_passes(payload, capsys):
    code = run_check(payload, "k", transport_returning(200, completion(json.dumps(VALID_OUTPUT))))
    assert code == 0 and "PASSED" in capsys.readouterr().out


def test_http_error_fails_and_shows_the_body(payload, capsys):
    code = run_check(payload, "k", transport_returning(403, {"error": "US developers only"}))
    out = capsys.readouterr().out
    assert code == 1 and "HTTP 403" in out and "US developers only" in out


def test_network_failure_fails_cleanly(payload, capsys):
    def handler(request):
        raise httpx.ConnectError("no route")

    assert run_check(payload, "k", httpx.MockTransport(handler)) == 1
    assert "FAILED" in capsys.readouterr().out


def test_unexpected_shape_fails(payload):
    assert run_check(payload, "k", transport_returning(200, {"choices": []})) == 1


def test_non_json_content_fails(payload):
    assert run_check(payload, "k", transport_returning(200, completion("not json"))) == 1


def test_null_content_fails(payload):
    assert run_check(payload, "k", transport_returning(200, completion(None))) == 1


def test_out_of_bounds_recipe_fails(payload, capsys):
    bad = json.loads(json.dumps(VALID_OUTPUT))
    bad["proposed_recipe_or_delta"]["filter"]["cutoff_hz"] = 99999
    assert run_check(payload, "k", transport_returning(200, completion(json.dumps(bad)))) == 1
    assert "filter.cutoff_hz" in capsys.readouterr().out
