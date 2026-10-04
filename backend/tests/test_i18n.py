"""The English layer (app/i18n.py): does `?lang=en` leave Vietnamese behind?

The rule these tests hold: a reader who picks English on a page must not meet a Vietnamese
sentence in it. Canal names, city names and headlines stay as they are - those are names.
"""
# ruff: noqa: RUF001 - Vietnamese text below is the input being translated

from __future__ import annotations

import json
import unicodedata
from datetime import UTC, datetime

import pytest
from app import i18n, waterways

from tests.factories import jpeg_bytes, noise_photo

SEGMENT = json.loads((waterways.DATA_DIR / "nhieu-loc-thi-nghe.geojson").read_text(encoding="utf-8"))["features"][1]
LON, LAT = SEGMENT["geometry"]["coordinates"][len(SEGMENT["geometry"]["coordinates"]) // 2]
SEGMENT_ID = SEGMENT["properties"]["id"]
DEG_PER_M = 1 / 111_320
OILY = {"observation_group": "river_health", "oil_sheen": "yes", "odor": "sewage", "water_color": "rainbow_sheen",
        "floating_trash": "little", "aquatic_life": "no", "nearby_place": "home", "contact": "children_nearby",
        "recent_rain": "flood_or_heavy", "observation_goal": "child_health"}


@pytest.fixture(autouse=True)
def no_rain_calls(monkeypatch):
    """The passport asks Open-Meteo for rain; tests never go on the network."""
    monkeypatch.setattr(waterways, "rain",
                        lambda *a, **k: [{"day": datetime.now(UTC).date().isoformat(), "mm": 25.0}])


@pytest.fixture
def seeded_river(client_with_database):
    """Three oil-sheen reports on one stretch: enough for a hotspot, an alert and a passport."""
    for i, north in enumerate((0.0, 30.0, 60.0), start=1):
        response = client_with_database.post(
            "/observations",
            data={"latitude": str(LAT + north * DEG_PER_M), "longitude": str(LON), "reporter_id": f"r{i}",
                  "answers": json.dumps(OILY)},
            files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=i)), "image/jpeg")})
        assert response.status_code == 201, response.text
    return SEGMENT_ID


# Fields that hold a name or foreign text; a Vietnamese canal name there is correct.
NAME_KEYS = {"waterway", "name", "title", "source", "city_name", "attribution", "segment", "user"}


def vietnamese(text: str) -> bool:
    """True when a string still carries Vietnamese letters (tones, ơ, ư, đ)."""
    return any(ord(c) > 127 and "WITH" in unicodedata.name(c, "") and
               unicodedata.name(c, "").startswith("LATIN") for c in text)


def leftovers(node, key=None, path="") -> list[str]:
    if isinstance(node, dict):
        return [line for k, v in node.items() for line in leftovers(v, k, f"{path}.{k}")]
    if isinstance(node, list):
        return [line for i, v in enumerate(node) for line in leftovers(v, key, f"{path}[{i}]")]
    if isinstance(node, str) and key not in NAME_KEYS and vietnamese(node):
        return [f"{path}: {node}"]
    return []


def test_normalize_falls_back_to_vietnamese():
    assert i18n.normalize(None) == "vi"
    assert i18n.normalize("en-GB") == "en"
    assert i18n.normalize("fr") == "vi"


def test_default_language_returns_the_payload_untouched():
    payload = {"limits": "Chỉ số dựa trên quan sát của người dân và model ảnh; không phải kết quả xét nghiệm nước, "
                         "không kết luận nước an toàn hay độc hại."}
    assert i18n.localize(payload, "vi") is payload


def test_report_can_request_both_languages_from_one_analysis(client, monkeypatch):
    from app.main import app

    calls = []
    detect = app.state.detector.detect

    def counted(*args, **kwargs):
        calls.append(True)
        return detect(*args, **kwargs)

    monkeypatch.setattr(app.state.detector, "detect", counted)
    response = client.post("/detect?lang=en", headers={"X-AquaPulse-Languages": "vi,en"},
                           files={"image": ("a.jpg", jpeg_bytes(noise_photo()), "image/jpeg")})
    assert response.status_code == 200, response.text
    views = response.json()
    assert len(calls) == 1
    assert "X-AquaPulse-Languages" in response.headers["vary"]
    assert set(views) == {"vi", "en"}
    assert views["en"] == i18n.localize(views["vi"], "en")
    assert views["vi"]["assessment"]["risk"] == views["en"]["assessment"]["risk"]
    assert views["vi"]["assessment"]["confidence"] == views["en"]["assessment"]["confidence"]


def test_bilingual_quality_error_keeps_status_and_details(client):
    response = client.post("/detect", headers={"X-AquaPulse-Languages": "vi,en"},
                           files={"image": ("a.jpg", jpeg_bytes(noise_photo(size=(64, 64))), "image/jpeg")})
    assert response.status_code == 422
    views = response.json()
    assert "quality" in views["vi"]["detail"]
    assert views["en"] == i18n.localize(views["vi"], "en")


@pytest.mark.parametrize(("vietnamese_text", "expected"), [
    ("Vàng", "Yellow"),
    ("trung bình", "medium"),
    ("váng dầu", "oil sheen"),
    ("1 cảnh báo đang mở", "1 open alert"),           # English counts one thing at a time
    ("3 cảnh báo đang mở", "3 open alerts"),
    ("Dấu hiệu gặp nhiều nhất: váng dầu (3 lần), mùi lạ (1 lần).",
     "Most frequent signs: oil sheen (3 times), unusual odour (1 time)."),
    ("Đoạn 2 · km 2,2–4,4", "Stretch 2 · km 2.2-4.4"),
])
def test_known_strings_become_english(vietnamese_text, expected):
    assert i18n.text(vietnamese_text) == expected


def test_a_sentence_with_an_embedded_comma_survives_the_list_split():
    said = ("Độ tin cậy trung bình vì phần lớn quan sát được gửi vào ban đêm, ảnh khó thấy màu nước và váng, "
            "chưa có ai xác minh tại hiện trường.")
    assert i18n.text(said) == ("Confidence is medium, because most observations were sent at night, when colour "
                               "and sheen are hard to see, and nobody has verified on site.")


def test_an_alert_message_is_translated_sentence_by_sentence():
    message = ("Cảnh báo mức vàng: 3 quan sát trong bán kính 500 m ghi nhận váng dầu và mùi lạ trong 22 giờ. "
               "Bằng chứng: 3 người khác nhau gửi ảnh; AI chỉ gán nghi ngờ ở 3 ảnh, chưa kết luận. "
               "Độ tin cậy trung bình (0,74), phần lớn ảnh chụp ban đêm. "
               "Hệ thống chưa kết luận nước bị nhiễm khuẩn hay độc tố. "
               "Cần nhóm tình nguyện viên xác minh tại hiện trường. "
               "Tránh tiếp xúc trực tiếp với nước cho đến khi có kết quả kiểm tra.")
    english = i18n.text(message)
    assert not vietnamese(english), english
    assert english.startswith("Yellow alert: 3 observations within 500 m reported oil sheen and unusual odour")


def test_an_unknown_sentence_comes_back_as_it_was():
    """A gap is a Vietnamese sentence, never a broken English one."""
    said = "Một câu chưa có trong từ điển dịch của hệ thống."
    assert i18n.text(said) == said


def test_names_are_never_translated():
    payload = {"waterway": "Kênh Nhiêu Lộc – Thị Nghè", "level": "yellow", "label": "váng dầu"}
    assert i18n.localize(payload, "en") == {"waterway": "Kênh Nhiêu Lộc – Thị Nghè", "level": "yellow",
                                            "label": "oil sheen"}


# --- the pages a reader sees, end to end ---------------------------------------------------

def test_the_catalog_reads_in_english(client):
    catalog = client.get("/vector-watch/catalog?lang=en").json()
    assert not leftovers(catalog), leftovers(catalog)[:5]
    river = next(g for g in catalog["groups"] if g["id"] == "river_health")
    assert river["label"] == "Rivers and canals: water surface, banks, floating litter"


def test_a_passport_reads_in_english(client_with_database, seeded_river):
    passport = client_with_database.get(f"/waterways/{seeded_river}/passport?include_demo=true&lang=en").json()
    assert not leftovers(passport), leftovers(passport)[:5]
    assert passport["indices"]["confidence_label"] in {"high", "medium", "low", "not available"}


def test_the_translator_answers_in_english(client_with_database, seeded_river):
    answer = client_with_database.get(
        f"/translator?question=children&segment_id={seeded_river}&include_demo=true&lang=en").json()
    assert not leftovers(answer), leftovers(answer)[:5]
    assert answer["question"] == "Should children play near here?"


def test_alerts_carry_english_evidence(client_with_database, seeded_river):
    alerts = client_with_database.get("/alerts?include_demo=true&lang=en").json()["alerts"]
    assert alerts, "the river demo should leave one alert open"
    assert not leftovers(alerts), leftovers(alerts)[:5]


def test_fhir_is_left_in_its_own_language(client_with_database, seeded_river):
    """A FHIR bundle goes to another system, not to a reader: the record keeps its text."""
    bundle = client_with_database.get(f"/fhir/waterways/{seeded_river}?include_demo=true&lang=en").json()
    assert bundle["resourceType"] == "Bundle"
    assert leftovers(bundle), "the FHIR bundle should not be translated"
