import json
from io import BytesIO

import httpx
import pytest
from app import vision
from PIL import Image

from tests.factories import scene_photo

GOOD_PAYLOAD = {
    "standing_water": {"detected": True, "certainty": "high"},
    "artificial_container": {"detected": True, "certainty": "high", "container_type": "used_tire"},
    "organic_waste": {"detected": True, "certainty": "medium"},
    "oil_sheen": {"detected": False, "certainty": "high"},
    "foam": {"detected": False, "certainty": "medium"},
    "mosquito_larvae": {"detected": False, "certainty": "low"},
    "fly_cluster": {"detected": False, "certainty": "low"},
    "requires_human_review": True,
    "explanation": "Ảnh cho thấy lốp xe có nước đọng và rác hữu cơ xung quanh.",
    "limitations": "Không thể xác định loài muỗi chỉ từ ảnh.",
}


def _ollama_response(payload):
    return httpx.Response(200, json={
        "model": vision.QWEN_MODEL,
        "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
        "done": True,
    })


def _gemini_response(payload):
    text = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(200, json={
        "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
    })


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _qwen(handler):
    return vision.QwenVision(client=_client(handler))


def _gemini(handler):
    return vision.GeminiVision("test-key", client=_client(handler))


def test_kimi_image_request_and_final_answer():
    def handler(request):
        assert request.headers["authorization"] == "Bearer test-key"
        assert str(request.url) == vision.KIMI_BASE_URL + "/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "kimi-k3"
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": "```json\n" + json.dumps(GOOD_PAYLOAD) + "\n```",
            "reasoning_content": "This must not be parsed as the answer.",
        }}]})

    client = vision.KimiVision("test-key", client=_client(handler))
    result = client.analyze(scene_photo())
    assert result.provider == "kimi"
    assert result.signals["standing_water"].detected is True
    assert client.sends_photo_off_device is True


def test_kimi_requires_key(monkeypatch):
    monkeypatch.setenv("AQUAPULSE_VISION_ENABLED", "1")
    monkeypatch.setenv("AQUAPULSE_VISION_PROVIDER", "kimi")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    assert vision.load_default_vision() is None
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    assert isinstance(vision.load_default_vision(), vision.KimiVision)


@pytest.mark.parametrize("choice", [
    {"message": {"content": ""}},
    {"finish_reason": "length", "message": {"content": "{}"}},
])
def test_kimi_rejects_empty_or_truncated_answer(choice):
    client = vision.KimiVision("test-key", client=_client(
        lambda request: httpx.Response(200, json={"choices": [choice]})))
    with pytest.raises(vision.VisionError, match="Kimi"):
        client.analyze(scene_photo())


# --- Qwen through Ollama (the default provider) ---------------------------------

def test_qwen_request_asks_ollama_for_schema_constrained_json():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen.update(json.loads(request.content))
        return _ollama_response(GOOD_PAYLOAD)

    _qwen(handler).analyze(scene_photo())
    assert seen["url"].endswith("/api/chat")
    assert seen["model"] == "qwen3-vl:2b-instruct-q8_0"  # Instruct, not the Thinking default tag
    assert seen["format"]["required"][0] == "standing_water"
    assert seen["stream"] is False
    assert seen["options"]["num_predict"] <= 1000  # a looping model must stop somewhere
    assert len(seen["messages"][0]["images"]) == 1


def test_qwen_analysis_is_parsed_and_marked_local():
    client = _qwen(lambda request: _ollama_response(GOOD_PAYLOAD))
    analysis = client.analyze(scene_photo(seed=11))
    assert analysis.provider == "qwen"
    assert analysis.signals["standing_water"].weight == pytest.approx(0.85)
    assert client.sends_photo_off_device is False


def test_qwen_empty_message_is_an_error():
    empty = httpx.Response(200, json={"message": {"role": "assistant", "content": ""}})
    with pytest.raises(vision.VisionError, match="Qwen"):
        _qwen(lambda request: empty).analyze(scene_photo(seed=12))


def test_ollama_has_model_checks_the_exact_tag():
    tags = httpx.Response(200, json={"models": [{"name": "qwen3-vl:2b", "model": "qwen3-vl:2b"}]})
    client = _client(lambda request: tags)
    # The Thinking tag being present is not enough.
    assert vision.ollama_has_model(vision.OLLAMA_URL, vision.QWEN_MODEL, client) is False
    assert vision.ollama_has_model(vision.OLLAMA_URL, "qwen3-vl:2b", client) is True


def test_ollama_unreachable_means_not_available():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    assert vision.ollama_has_model(vision.OLLAMA_URL, vision.QWEN_MODEL, _client(refuse)) is False


def test_default_provider_is_qwen_when_ollama_has_the_model(monkeypatch):
    monkeypatch.delenv("AQUAPULSE_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("AQUAPULSE_VISION_ENABLED", raising=False)
    monkeypatch.setattr(vision, "ollama_has_model", lambda *args: True)
    assert isinstance(vision.load_default_vision(), vision.QwenVision)
    monkeypatch.setattr(vision, "ollama_has_model", lambda *args: False)
    assert vision.load_default_vision() is None


# --- behaviour shared by every provider -----------------------------------------

def test_certainty_maps_to_weights():
    analysis = _qwen(lambda request: _ollama_response(GOOD_PAYLOAD)).analyze(scene_photo())
    assert analysis.signals["organic_waste"].weight == pytest.approx(0.6)
    # Not detected: no weight, whatever the model's certainty about the absence.
    assert analysis.signals["oil_sheen"].weight == 0.0
    assert analysis.signals["artificial_container"].container_type == "used_tire"
    assert analysis.dropped_claims == ()


def test_out_of_scope_text_is_dropped_and_sent_to_review():
    payload = {**GOOD_PAYLOAD,
               "requires_human_review": False,
               "explanation": "Muỗi trong ảnh mang virus sốt xuất huyết.",
               "limitations": "Nước này có vi khuẩn E. coli."}
    analysis = _qwen(lambda request: _ollama_response(payload)).analyze(scene_photo(seed=3))
    assert "virus" not in analysis.explanation
    assert analysis.limitations == ""
    assert analysis.requires_human_review is True
    assert len(analysis.dropped_claims) == 2


def test_unknown_certainty_falls_back_to_low():
    payload = {**GOOD_PAYLOAD, "organic_waste": {"detected": True, "certainty": "chắc chắn lắm"}}
    analysis = _qwen(lambda request: _ollama_response(payload)).analyze(scene_photo(seed=4))
    assert analysis.signals["organic_waste"].certainty == "low"


def test_same_photo_is_answered_from_cache():
    calls = []

    def handler(request):
        calls.append(1)
        return _ollama_response(GOOD_PAYLOAD)

    client = _qwen(handler)
    photo = scene_photo(seed=5)
    first = client.analyze(photo)
    second = client.analyze(photo)
    assert len(calls) == 1
    assert first.cached is False
    assert second.cached is True


def test_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr(vision.time, "sleep", lambda seconds: None)
    responses = [httpx.Response(503, json={}), _ollama_response(GOOD_PAYLOAD)]
    analysis = _qwen(lambda request: responses.pop(0)).analyze(scene_photo(seed=6))
    assert analysis.signals["standing_water"].detected is True


def test_invalid_json_is_an_error():
    broken = httpx.Response(200, json={"message": {"content": "xin chào, không phải JSON"}})
    with pytest.raises(vision.VisionError, match="JSON"):
        _qwen(lambda request: broken).analyze(scene_photo(seed=8))


def test_encoded_image_drops_exif_and_shrinks():
    data = vision.encode_image(scene_photo(size=(4000, 3000)))
    with Image.open(BytesIO(data)) as reopened:
        assert max(reopened.size) == vision.MAX_IMAGE_SIDE
        assert not reopened.getexif()


# --- Gemini (optional provider) --------------------------------------------------

def test_gemini_request_carries_the_schema_and_the_key():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        seen["api_key"] = request.headers.get("x-goog-api-key")
        return _gemini_response(GOOD_PAYLOAD)

    analysis = _gemini(handler).analyze(scene_photo())
    assert seen["api_key"] == "test-key"
    assert seen["model"] == vision.GEMINI_MODEL
    assert seen["response_format"]["schema"]["properties"]["foam"]["properties"]["certainty"]["enum"] == [
        "low", "medium", "high"]
    assert analysis.provider == "gemini"


def test_gemini_does_not_retry_a_bad_key(monkeypatch):
    monkeypatch.setattr(vision.time, "sleep", lambda seconds: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": "invalid key"})

    with pytest.raises(vision.VisionError, match="401"):
        _gemini(handler).analyze(scene_photo(seed=7))
    assert len(calls) == 1


def test_gemini_failed_status_is_an_error():
    failed = httpx.Response(200, json={"status": "failed", "errors": [{"message": "safety"}]})
    with pytest.raises(vision.VisionError):
        _gemini(lambda request: failed).analyze(scene_photo(seed=9))


def test_gemini_needs_a_key(monkeypatch):
    monkeypatch.setenv("AQUAPULSE_VISION_PROVIDER", "gemini")
    monkeypatch.delenv("AQUAPULSE_VISION_ENABLED", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert vision.load_default_vision() is None
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert isinstance(vision.load_default_vision(), vision.GeminiVision)


def test_vision_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("AQUAPULSE_VISION_ENABLED", "0")
    monkeypatch.setattr(vision, "ollama_has_model", lambda *args: True)
    assert vision.load_default_vision() is None


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.delenv("AQUAPULSE_VISION_ENABLED", raising=False)
    monkeypatch.setenv("AQUAPULSE_VISION_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="qwen hoặc gemini"):
        vision.load_default_vision()


def test_claimed_oil_or_foam_always_goes_to_a_person():
    """The model said 'no review needed' while claiming oil sheen on clean water."""
    payload = {**GOOD_PAYLOAD, "requires_human_review": False,
               "oil_sheen": {"detected": True, "certainty": "high"}}
    analysis = _qwen(lambda request: _ollama_response(payload)).analyze(scene_photo(seed=21))
    assert analysis.requires_human_review is True
    assert analysis.review_reasons == ("oil_sheen",)


def test_plain_findings_keep_the_model_review_flag():
    payload = {**GOOD_PAYLOAD, "requires_human_review": False}
    analysis = _qwen(lambda request: _ollama_response(payload)).analyze(scene_photo(seed=22))
    assert analysis.requires_human_review is False
    assert analysis.review_reasons == ()


def test_container_type_is_required_by_the_schema():
    container = vision.RESPONSE_SCHEMA["properties"]["artificial_container"]
    assert "container_type" in container["required"]


def test_free_text_fields_have_a_length_cap():
    props = vision.RESPONSE_SCHEMA["properties"]
    assert props["explanation"]["maxLength"] == vision.EXPLANATION_MAX_CHARS
    assert props["limitations"]["maxLength"] == vision.LIMITATIONS_MAX_CHARS
