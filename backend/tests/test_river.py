"""AquaPulse river brief: river form and scores, yellow until checked, evidence alerts,
segment passports, the translator, and FHIR export."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from app import waterways
from app.domain import find_out_of_scope_claims
from app.features import FeatureSet
from app.fusion import ReportAnswers
from app.pipeline import score
from app.vision import Signal, VisionAnalysis

from tests.factories import jpeg_bytes, noise_photo

SEGMENT = json.loads((waterways.DATA_DIR / "nhieu-loc-thi-nghe.geojson").read_text(encoding="utf-8"))["features"][1]
LON, LAT = SEGMENT["geometry"]["coordinates"][len(SEGMENT["geometry"]["coordinates"]) // 2]
SEGMENT_ID = SEGMENT["properties"]["id"]
DEG_PER_M = 1 / 111_320
VOLUNTEER = {"Authorization": "Bearer vol-token-123"}
EXPERT = {"Authorization": "Bearer exp-token-789"}
NAMES = ("standing_water", "artificial_container", "organic_waste", "oil_sheen", "foam", "mosquito_larvae",
         "fly_cluster")
OILY = {"observation_group": "river_health", "oil_sheen": "yes", "odor": "sewage", "water_color": "rainbow_sheen",
        "floating_trash": "little", "aquatic_life": "no", "nearby_place": "home", "contact": "children_nearby",
        "recent_rain": "flood_or_heavy", "observation_goal": "child_health"}
CLEAN = {"observation_group": "river_health", "oil_sheen": "no", "odor": "none", "water_color": "normal", "foam": "no",
         "floating_trash": "none", "aquatic_life": "yes", "nearby_place": "home", "contact": "passing"}


@pytest.fixture(autouse=True)
def no_rain_calls(monkeypatch):
    """The passport asks Open-Meteo for rain; tests never go on the network."""
    monkeypatch.setattr(waterways, "rain", lambda *a, **k: [{"day": datetime.now(UTC).date().isoformat(), "mm": 25.0}])


@pytest.fixture
def reviewers(monkeypatch):
    monkeypatch.setenv("AQUAPULSE_REVIEWERS", "volunteer:vol-01:vol-token-123,expert:exp-01:exp-token-789")


def scored(answers, vision=None):
    return score(FeatureSet({}, 0.0, None), ReportAnswers(**answers), vision, 0, vision is not None)


# --- the river form and its three scores ---------------------------------------------------

def test_oil_report_is_suspected_yellow_and_goes_to_a_person():
    _, assessment, review, watch = scored(OILY)
    assert watch.group_score > 0.5 and watch.eco_score < 0.5 and watch.human_contact_risk > 0.6
    assert assessment.level == "yellow"                       # not orange before anyone checked
    assert "chưa kết luận" in assessment.action
    assert review.decision == "verify"
    assert "Tránh tiếp xúc trực tiếp với nước" in watch.statement
    assert any("trẻ" in note for note in watch.notes)         # the child-health goal shapes the advice


def test_clean_stretch_scores_healthy():
    _, assessment, _, watch = scored(CLEAN)
    assert watch.group_score < 0.2 and watch.eco_score > 0.9 and assessment.level == "green"


def test_vision_suspicion_becomes_a_question_with_its_certainty():
    vision = VisionAnalysis({n: Signal(n == "oil_sheen", "medium") for n in NAMES}, False, "", "", "qwen", "t", 0.0)
    _, _, review, _ = scored({**CLEAN, "oil_sheen": "unknown"}, vision)
    assert review.questions == [("Ảnh cho thấy khả năng có váng dầu, độ tin cậy 70%. "
                                 "Bạn có thấy ánh cầu vồng hoặc mùi xăng dầu không?")]
    assert review.ask_reporter


def test_dead_fish_no_does_not_erase_a_carcass_on_the_bank():
    fusion, *_ = scored({"observation_group": "dead_animal", "dead_animal_or_feces": "yes", "dead_fish": "no"})
    assert fusion.signals["dead_animal"].present


# --- the demo story through the API --------------------------------------------------------

def report(client, answers, reporter, seed, north_m=0.0):
    response = client.post(
        "/observations",
        data={"latitude": str(LAT + north_m * DEG_PER_M), "longitude": str(LON), "reporter_id": reporter,
              "answers": json.dumps(answers)},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=seed)), "image/jpeg")})
    assert response.status_code == 201, response.text
    return response.json()


def test_three_oil_reports_make_a_yellow_alert_with_evidence_then_orange_after_a_volunteer(
        client_with_database, reviewers):
    first = report(client_with_database, OILY, "r1", 1)
    assert first["segment"]["id"] == SEGMENT_ID
    report(client_with_database, OILY, "r2", 2, 30)
    third = report(client_with_database, OILY, "r3", 3, 60)
    assert third["alert_changes"] == [{"alert_id": third["alert_changes"][0]["alert_id"], "change": "opened",
                                       "level": "yellow"}]
    alert = client_with_database.get("/alerts").json()["alerts"][0]
    proof = alert["evidence"]
    assert proof["what"]["reports"] == 3 and proof["what"]["signals"][0]["label"] == "váng dầu"
    assert proof["evidence"]["reporters"] == 3 and proof["evidence"]["confirmed_on_site"] == 0
    assert proof["verifier"] == "Cần nhóm tình nguyện viên xác minh tại hiện trường"
    assert proof["advice"].startswith("Tránh tiếp xúc trực tiếp với nước")

    task = first["verification_task_id"]
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER, json={"verdict": "confirmed"})
    alert = client_with_database.get("/alerts").json()["alerts"][0]
    assert alert["level"] == "orange"
    assert alert["evidence"]["verifier"] == "Cần chuyên gia môi trường lấy mẫu"

    notices = client_with_database.get("/notifications", params={"latitude": LAT, "longitude": LON}).json()["area"]
    messages = [n["message"] for n in notices if n["kind"].startswith("alert")]
    assert len(messages) == 2
    for message in messages:
        assert "Bằng chứng:" in message and "Độ tin cậy" in message and "Tránh tiếp xúc" in message
        assert find_out_of_scope_claims(message) == []


def test_passport_gives_the_five_indices_and_explains_them(client_with_database):
    report(client_with_database, CLEAN, "r1", 10)
    report(client_with_database, OILY, "r2", 11, 20)
    passport = client_with_database.get(f"/waterways/{SEGMENT_ID}/passport").json()
    ix = passport["indices"]
    assert {"eco", "risk", "confidence", "trend", "human_health"} <= ix.keys()
    assert ix["reports_7d"] == 2 and ix["anomalies_7d"] == 1
    assert passport["participation"]["reporters"] == 2
    assert passport["life"] == {**passport["life"], "seen_alive": 1, "not_seen": 1}
    assert any("Mưa lớn 25 mm" in sentence for sentence in passport["explanation"])
    assert any("quan sát ban ngày" in action or "Không để trẻ" in action for action in passport["actions"])
    assert passport["segment"]["geometry"]["type"] == "LineString"
    overview = client_with_database.get("/waterways").json()["segments"]
    waterways_seen = {s["waterway"] for s in overview}
    assert SEGMENT["properties"]["waterway"] in waterways_seen and len(waterways_seen) >= 6  # the city's canals
    assert sum(1 for s in overview if s["id"].startswith("nhieu-loc-thi-nghe-")) == 4
    assert client_with_database.get("/waterways/nope/passport").status_code == 404


def test_night_reports_lower_confidence_and_ask_for_daytime_ones():
    today = datetime.now(UTC).date()
    rows = [{"confidence": 0.9, "local_hour": 22, "local_day": today, "group_score": 0.7, "eco_score": 0.3,
             "human_contact_risk": 0.5, "answers": {"oil_sheen": "yes"}, "reporter_id": f"r{i}",
             "confirmed_on_site": False} for i in range(3)]
    ix = waterways.indices(rows, today)
    assert ix["confidence"] == pytest.approx(0.72) and ix["confidence_label"] == "trung bình"
    sentences, actions = waterways.explain(ix, rows, None, [], today)
    assert any("ban đêm" in s for s in sentences)
    assert "Nên bổ sung 3 quan sát ban ngày trước khi phát cảnh báo chính thức." in actions


def test_rain_is_read_from_open_meteo_and_fails_soft(monkeypatch):
    monkeypatch.undo()  # the real function, with a fake transport
    waterways._rain_cache.clear()
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={"daily": {"time": ["2026-09-17", "2026-09-18"], "precipitation_sum": [11.0, 22.3]}})))
    assert waterways.rain(10.79, 106.68, client=ok)[-1] == {"day": "2026-09-18", "mm": 22.3}
    waterways._rain_cache.clear()
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert waterways.rain(10.79, 106.68, client=down) is None


# --- translator --------------------------------------------------------------------------

@pytest.mark.parametrize("question", ["children", "odor", "after_rain", "biodiversity"])
def test_translator_always_says_what_it_used_and_what_it_does_not_know(client_with_database, question):
    report(client_with_database, OILY, "r1", 20)
    body = client_with_database.get("/translator", params={"question": question, "segment_id": SEGMENT_ID}).json()
    assert body["answer"] and body["data_used"] and body["certainty"] and body["unknown"]
    assert "không phải khuyến nghị y tế" in body["disclaimer"]
    for text in (body["answer"], body["advice"], *body["unknown"]):
        assert find_out_of_scope_claims(text) == []


def test_translator_children_says_not_yet_near_an_oil_report(client_with_database):
    report(client_with_database, OILY, "r1", 21)
    body = client_with_database.get("/translator", params={"question": "children", "segment_id": SEGMENT_ID}).json()
    assert body["answer"].startswith("Chưa nên")
    assert client_with_database.get("/translator", params={"question": "children"}).status_code == 422
    assert client_with_database.get("/translator", params={"question": "weather"}).status_code == 422


# --- FHIR -------------------------------------------------------------------------------

def test_fhir_bundle_has_location_riskassessment_and_observations(client_with_database):
    first = report(client_with_database, OILY, "r1", 30)
    bundle = client_with_database.get(f"/fhir/waterways/{SEGMENT_ID}")
    assert bundle.headers["content-type"].startswith("application/fhir+json")
    kinds = [e["resource"]["resourceType"] for e in bundle.json()["entry"]]
    assert kinds == ["Location", "RiskAssessment", "Observation"]
    obs = client_with_database.get(f"/fhir/Observation/{first['id']}").json()
    assert obs["status"] == "preliminary" and obs["subject"] == {"reference": f"Location/{SEGMENT_ID}"}
    assert "reporter" not in json.dumps(obs) and "r1" not in json.dumps(obs)
    codes = {c["code"]["coding"][0]["code"] for c in obs["component"]}
    assert {"oil_sheen", "risk-score", "eco-score", "confidence", "human-health"} <= codes


def test_reports_far_from_the_canal_have_no_segment(client_with_database):
    far = report(client_with_database, CLEAN, "r1", 40, north_m=3000)
    assert far["segment"] is None


# --- two ways to analyse a photo ------------------------------------------------------------

def test_scene_mode_runs_without_the_container_detector(client_with_database):
    """Option 2: river surface, litter, oil sheen. The detector never looked, so it must not
    be counted as a source that saw nothing."""
    response = client_with_database.post(
        "/observations?with_detector=false",
        data={"latitude": str(LAT), "longitude": str(LON), "reporter_id": "r1", "answers": json.dumps(OILY)},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=60)), "image/jpeg")})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["detector"] == {**body["detector"], "requested": False, "ran": False}
    assert body["detections"] == [] and body["water"]["available"] is False
    assert "detector" not in body["fusion"]["sources_used"]
    assert any("không chạy model nhận diện vật chứa" in note.lower() for note in body["fusion"]["notes"])
    assert body["assessment"]["confidence"] > 0.5      # a missing source is not a penalty in itself


def test_container_mode_still_uses_the_detector(client_with_database):
    body = client_with_database.post(
        "/observations",
        data={"latitude": str(LAT), "longitude": str(LON), "reporter_id": "r2",
              "answers": json.dumps({"observation_group": "aedes_breeding_risk", "water_stagnant": "yes"})},
        files={"image": ("b.jpg", jpeg_bytes(noise_photo(seed=61)), "image/jpeg")}).json()
    assert body["detector"]["ran"] is True
    assert "detector" in body["fusion"]["sources_used"]


def test_detect_without_a_model_works_in_scene_mode(client):
    from app.main import app
    detector, app.state.detector = app.state.detector, None
    try:
        with_model = client.post("/detect?with_detector=false",
                                 files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=62)), "image/jpeg")})
        assert with_model.status_code == 200 and with_model.json()["detector"]["available"] is False
        assert client.post("/detect", files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=63)), "image/jpeg")}
                           ).status_code == 503
    finally:
        app.state.detector = detector
