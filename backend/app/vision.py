"""Vision-language model: context and explanation, never the verdict.

Division of labour (flow step N):
    YOLO        finds objects it was trained on
    VLM         reads the scene and explains it, including signals we have no
                training data for (organic waste, foam, oil sheen)
    rule engine scores the risk
    people      verify

Two providers share everything except the HTTP call:

* `QwenVision` (default): Qwen3-VL-2B-Instruct served by Ollama on this machine.
  Free, and the citizen's photo never leaves the server. Ollama constrains decoding
  to the JSON schema, which matters for a 2B model that would otherwise drift.
* `GeminiVision`: Google's API. Stronger, but paid and the photo goes to Google.

Three deliberate departures from section 10 of the plan:

1. The plan's schema asks for a float `confidence` per signal, but its own prompt
   lists the levels low / medium / high. Floats from a language model are not
   calibrated - 0.86 and 0.83 mean nothing next to each other - so the schema uses
   the three levels and `CERTAINTY_WEIGHT` maps them to numbers in one visible place.

2. Every piece of free text is checked with `find_out_of_scope_claims` before it is
   returned. A model that writes "muỗi mang virus sốt xuất huyết" would break the
   product's promises from section 1, so that text is dropped and the observation is
   sent to human review instead.

3. Results are cached by image bytes. The same photo re-submitted costs nothing and
   gives the same answer.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
from PIL import Image

from app.domain import find_out_of_scope_claims
from app.privacy import blur_faces

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL = "gemini-3.6-flash"
OLLAMA_URL = "http://127.0.0.1:11434"
# The plain "qwen3-vl:2b" tag is the Thinking variant; the Instruct one is asked for by name.
# q8_0 is near-lossless against bf16 and leaves room on a 6 GB GPU.
QWEN_MODEL = "qwen3-vl:2b-instruct-q8_0"
KIMI_MODEL = "kimi-k3"
KIMI_BASE_URL = "https://ws-ojz5frpqw24ibm8d.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

REQUEST_TIMEOUT = 60.0  # a local 2B model on a laptop GPU needs a few seconds per photo
MAX_ATTEMPTS = 3
MAX_IMAGE_SIDE = 1024  # smaller image, fewer vision tokens; plenty for scene context
CACHE_SIZE = 256

SIGNALS: tuple[str, ...] = (
    "standing_water",
    "artificial_container",
    "organic_waste",
    "oil_sheen",
    "foam",
    "mosquito_larvae",
    "fly_cluster",
)

CONTAINER_TYPES: tuple[str, ...] = (
    "used_tire", "bucket_or_jar", "flower_pot", "bottle_or_can",
    "coconut_shell", "blocked_drain", "other", "none",
)

EXPLANATION_MAX_CHARS = 300
LIMITATIONS_MAX_CHARS = 200

CERTAINTY_LEVELS: tuple[str, ...] = ("low", "medium", "high")
# One visible place where the model's words become numbers for the rule engine.
CERTAINTY_WEIGHT: dict[str, float] = {"low": 0.3, "medium": 0.6, "high": 0.85}

# No product name in the prompt: the 2B model echoed it back into its explanations.
PROMPT = """Bạn là trợ lý phân tích môi trường đô thị.

Nguyên tắc bắt buộc:
1. Không xác định loài muỗi hay tác nhân gây bệnh chỉ từ ảnh.
2. Chỉ mô tả thứ nhìn thấy rõ trong ảnh. Không suy đoán.
3. Không đưa ra chẩn đoán y tế, không kết luận nước nhiễm khuẩn.
4. Không đề xuất phun hóa chất.
5. Nếu không chắc, đặt requires_human_review = true.

Với mỗi dấu hiệu:
- detected = true chỉ khi nhìn thấy rõ ràng. Nếu phải đoán thì để false.
- certainty là mức chắc chắn của bạn: low, medium hoặc high.
- container_type là loại vật chứa chính trong ảnh, hoặc none.

explanation: một câu ngắn tiếng Việt, mô tả thứ nhìn thấy.
limitations: một câu ngắn tiếng Việt. Không chép lại các nguyên tắc ở trên."""

PROMPT_EN = """You are an assistant that analyses urban environments.

Rules you must follow:
1. Never identify a mosquito species or a disease agent from a photo.
2. Describe only what is clearly visible. Do not speculate.
3. Give no medical diagnosis and never conclude that water is contaminated.
4. Never suggest spraying chemicals.
5. When unsure, set requires_human_review = true.

For each sign:
- detected = true only when it is clearly visible. If you have to guess, leave it false.
- certainty is how sure you are: low, medium or high.
- container_type is the main container in the photo, or none.

explanation: one short English sentence describing what is visible.
limitations: one short English sentence. Do not repeat the rules above."""

PROMPTS = {"vi": PROMPT, "en": PROMPT_EN}


def prompt_for(lang: str | None) -> str:
    """The model answers in the language the reader is reading."""
    return PROMPTS.get((lang or "vi")[:2].lower(), PROMPT)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{
            signal: {
                "type": "object",
                "properties": {
                    "detected": {"type": "boolean"},
                    "certainty": {"type": "string", "enum": list(CERTAINTY_LEVELS)},
                    **({"container_type": {"type": "string", "enum": list(CONTAINER_TYPES)}}
                       if signal == "artificial_container" else {}),
                },
                "required": ["detected", "certainty",
                             *(["container_type"] if signal == "artificial_container" else [])],
            }
            for signal in SIGNALS
        },
        "requires_human_review": {"type": "boolean"},
        # maxLength makes Ollama's grammar close the string. Without it Qwen3-VL-2B looped
        # on one sentence until the context ran out, leaving the JSON unterminated.
        "explanation": {"type": "string", "maxLength": EXPLANATION_MAX_CHARS},
        "limitations": {"type": "string", "maxLength": LIMITATIONS_MAX_CHARS},
    },
    "required": [*SIGNALS, "requires_human_review", "explanation", "limitations"],
}

RETRYABLE_STATUS = (429, 500, 502, 503, 504)

# Signals the model may claim that a person must confirm before anything acts on them.
# On test photos Qwen3-VL-2B claimed oil sheen and foam "with high certainty" on clean
# water, and section 9 already asks for expert checks on oil and on larvae.
REVIEW_ON_DETECTION: tuple[str, ...] = ("oil_sheen", "foam", "mosquito_larvae", "fly_cluster")


class VisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Signal:
    detected: bool
    certainty: str
    container_type: str | None = None

    @property
    def weight(self) -> float:
        """Numeric strength for the rule engine; 0 when the model saw nothing."""
        return CERTAINTY_WEIGHT.get(self.certainty, 0.0) if self.detected else 0.0

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "detected": self.detected,
            "certainty": self.certainty,
            "weight": round(self.weight, 2),
        }
        if self.container_type:
            data["container_type"] = self.container_type
        return data


@dataclass(frozen=True)
class VisionAnalysis:
    signals: dict[str, Signal]
    requires_human_review: bool
    explanation: str
    limitations: str
    provider: str
    model: str
    elapsed_ms: float
    cached: bool = False
    dropped_claims: tuple[str, ...] = field(default_factory=tuple)
    review_reasons: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisionAnalysis:
        """Inverse of as_dict, to re-score a stored report without calling the model again."""
        return cls(
            signals={
                name: Signal(s["detected"], s["certainty"], s.get("container_type"))
                for name, s in data["signals"].items()
            },
            requires_human_review=data["requires_human_review"],
            explanation=data["explanation"],
            limitations=data["limitations"],
            provider=data["provider"],
            model=data["model"],
            elapsed_ms=data["elapsed_ms"],
            cached=data.get("cached", False),
            dropped_claims=tuple(data.get("dropped_claims", ())),
            review_reasons=tuple(data.get("review_reasons", ())),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "cached": self.cached,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "signals": {name: signal.as_dict() for name, signal in self.signals.items()},
            "requires_human_review": self.requires_human_review,
            "explanation": self.explanation,
            "limitations": self.limitations,
            "dropped_claims": list(self.dropped_claims),
            "review_reasons": list(self.review_reasons),
        }


def encode_image(image: Image.Image, max_side: int = MAX_IMAGE_SIDE) -> bytes:
    """Re-encode from decoded pixels: EXIF, including GPS, is left behind."""
    picture = image.convert("RGB")
    if max(picture.size) > max_side:
        scale = max_side / max(picture.size)
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)))
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def parse_analysis(payload: dict[str, Any], provider: str, model: str, elapsed_ms: float) -> VisionAnalysis:
    """Validate the model's JSON and strip any text that breaks the product's non-claims."""
    signals: dict[str, Signal] = {}
    for name in SIGNALS:
        raw = payload.get(name) or {}
        certainty = raw.get("certainty")
        signals[name] = Signal(
            detected=bool(raw.get("detected")),
            certainty=certainty if certainty in CERTAINTY_LEVELS else "low",
            container_type=raw.get("container_type") if name == "artificial_container" else None,
        )

    explanation = str(payload.get("explanation", "")).strip()
    limitations = str(payload.get("limitations", "")).strip()
    review = bool(payload.get("requires_human_review", True))

    review_reasons = [name for name in REVIEW_ON_DETECTION if signals[name].detected]
    if review_reasons:
        review = True

    dropped: list[str] = []
    for label, text in (("explanation", explanation), ("limitations", limitations)):
        claims = find_out_of_scope_claims(text)
        if claims:
            dropped.extend(claims)
            if label == "explanation":
                explanation = ""
            else:
                limitations = ""
    if dropped:
        # The model wrote something outside what this product may claim: drop the text
        # and let a person look at the photo.
        review = True
        explanation = explanation or "Phần giải thích của AI đã bị lọc vì vượt phạm vi cho phép."

    return VisionAnalysis(
        signals=signals,
        requires_human_review=review,
        explanation=explanation,
        limitations=limitations,
        provider=provider,
        model=model,
        elapsed_ms=elapsed_ms,
        dropped_claims=tuple(dict.fromkeys(dropped)),
        review_reasons=tuple(review_reasons),
    )


class VisionClient:
    """Shared flow: encode, cache, call the provider, parse, filter."""

    provider = "base"
    # Whether the photo leaves this machine; shown to the user next to the result.
    sends_photo_off_device = True

    def __init__(self, model: str, client: httpx.Client | None = None):
        self.model = model
        self.client = client or httpx.Client(timeout=REQUEST_TIMEOUT)
        self._cache: OrderedDict[str, VisionAnalysis] = OrderedDict()

    def analyze(self, image: Image.Image, lang: str = "vi") -> VisionAnalysis:
        if self.sends_photo_off_device:
            image, _ = blur_faces(image)  # section 22: no faces leave the server
        image_bytes = encode_image(image)
        prompt = prompt_for(lang)
        # The same photo has one answer per language, so the language belongs in the key.
        key = hashlib.sha256(image_bytes).hexdigest() + ":" + ("en" if prompt is PROMPT_EN else "vi")
        if key in self._cache:
            self._cache.move_to_end(key)
            return replace(self._cache[key], cached=True)

        started = time.perf_counter()
        text = self._generate(image_bytes, prompt)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VisionError(f"{self.provider} trả về JSON không hợp lệ.") from exc
        if not isinstance(payload, dict):
            raise VisionError(f"{self.provider} trả về JSON không đúng dạng.")

        analysis = parse_analysis(payload, self.provider, self.model, (time.perf_counter() - started) * 1000)
        self._cache[key] = analysis
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return analysis

    def _generate(self, image_bytes: bytes, prompt: str) -> str:
        raise NotImplementedError

    def _post(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.client.post(url, json=body, headers=headers or {})
            except httpx.HTTPError as exc:
                last_error = VisionError(f"Không gọi được {self.provider}: {exc}")
            else:
                if response.status_code == 200:
                    return response.json()
                # Rate limits and server errors are worth another try; 4xx will not fix itself.
                if response.status_code not in RETRYABLE_STATUS:
                    raise VisionError(f"{self.provider} trả về HTTP {response.status_code}: {response.text[:200]}")
                last_error = VisionError(f"{self.provider} trả về HTTP {response.status_code}")
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(0.5 * 2**attempt)
        raise last_error or VisionError(f"Gọi {self.provider} thất bại.")


class QwenVision(VisionClient):
    """Qwen3-VL-2B-Instruct through Ollama's chat API, with schema-constrained output."""

    provider = "qwen"
    sends_photo_off_device = False

    def __init__(self, base_url: str = OLLAMA_URL, model: str = QWEN_MODEL, client: httpx.Client | None = None):
        super().__init__(model, client)
        self.base_url = base_url.rstrip("/")

    def build_request(self, image_bytes: bytes, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }],
            "format": RESPONSE_SCHEMA,
            "stream": False,
            "keep_alive": "30m",  # keep the weights on the GPU between demo photos
            # Greedy decoding at temperature 0 sent the 2B model into repetition loops;
            # a little temperature and a repeat penalty stop that. num_predict is the
            # backstop, well above the ~400 tokens a complete answer takes.
            "options": {"temperature": 0.2, "repeat_penalty": 1.15, "num_predict": 700, "num_ctx": 4096},
        }

    def _generate(self, image_bytes: bytes, prompt: str) -> str:
        body = self._post(f"{self.base_url}/api/chat", self.build_request(image_bytes, prompt))
        content = (body.get("message") or {}).get("content")
        if not content:
            raise VisionError("Qwen không trả về nội dung nào.")
        return content


class KimiVision(VisionClient):
    """Kimi through Model Studio's OpenAI-compatible image API."""

    provider = "kimi"

    def __init__(self, api_key: str, base_url: str = KIMI_BASE_URL,
                 model: str = KIMI_MODEL, client: httpx.Client | None = None):
        super().__init__(model, client)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def build_request(self, image_bytes: bytes, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt + "\nReturn only JSON matching this schema:\n"
                 + json.dumps(RESPONSE_SCHEMA, ensure_ascii=False)},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")}},
            ]}],
            "stream": False,
            "enable_thinking": False,
            "max_tokens": 2048,
        }

    def _generate(self, image_bytes: bytes, prompt: str) -> str:
        body = self._post(f"{self.base_url}/chat/completions",
                          self.build_request(image_bytes, prompt),
                          {"Authorization": f"Bearer {self.api_key}"})
        choices = body.get("choices") or []
        if not choices:
            raise VisionError("Kimi returned no answer.")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise VisionError("Kimi answer exceeded the token limit.")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise VisionError("Kimi returned no answer.")
        text = content.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return text


class GeminiVision(VisionClient):
    """Gemini through the Interactions API. Paid, and the photo leaves the server."""

    provider = "gemini"

    def __init__(self, api_key: str, model: str = GEMINI_MODEL, client: httpx.Client | None = None):
        super().__init__(model, client)
        self.api_key = api_key

    def build_request(self, image_bytes: bytes, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": [
                {"type": "text", "text": prompt},
                {"type": "image", "mime_type": "image/jpeg",
                 "data": base64.b64encode(image_bytes).decode("ascii")},
            ],
            "response_format": {"type": "text", "mime_type": "application/json", "schema": RESPONSE_SCHEMA},
            "temperature": 0,
        }

    def _generate(self, image_bytes: bytes, prompt: str) -> str:
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        return read_gemini_text(self._post(GEMINI_URL, self.build_request(image_bytes, prompt), headers))


def read_gemini_text(body: dict[str, Any]) -> str:
    if body.get("status") == "failed":
        raise VisionError(f"Gemini trả về lỗi: {body.get('errors')}")
    if body.get("output_text"):
        return body["output_text"]
    for step in body.get("steps", []):
        if step.get("type") == "model_output":
            for part in step.get("content", []):
                if part.get("type") == "text" and part.get("text"):
                    return part["text"]
    raise VisionError("Gemini không trả về nội dung nào.")


def ollama_has_model(base_url: str, model: str, client: httpx.Client | None = None) -> bool:
    try:
        response = (client or httpx.Client(timeout=2.0)).get(f"{base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return any(m.get("name") == model or m.get("model") == model for m in response.json().get("models", []))


def load_default_vision() -> VisionClient | None:
    """Pick the provider from AQUAPULSE_VISION_PROVIDER (qwen by default).

    Returns None, which turns the feature off, when the provider is not reachable.
    """
    if os.environ.get("AQUAPULSE_VISION_ENABLED", "1") not in ("1", "true", "True"):
        return None
    provider = os.environ.get("AQUAPULSE_VISION_PROVIDER", "qwen").lower()
    if provider == "kimi":
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        return KimiVision(api_key, os.environ.get("KIMI_BASE_URL", KIMI_BASE_URL),
                          os.environ.get("KIMI_MODEL", KIMI_MODEL)) if api_key else None
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        return GeminiVision(api_key, os.environ.get("GEMINI_MODEL", GEMINI_MODEL)) if api_key else None
    if provider == "qwen":
        base_url = os.environ.get("OLLAMA_URL", OLLAMA_URL)
        model = os.environ.get("QWEN_MODEL", QWEN_MODEL)
        return QwenVision(base_url, model) if ollama_has_model(base_url, model) else None
    raise ValueError(f"AQUAPULSE_VISION_PROVIDER không hợp lệ: {provider!r} (dùng qwen hoặc gemini)")
