"""Sections 17-22: alerts, notifications, points, community tasks, public views, metrics."""

import json

import numpy as np
import pytest
from app import alerts, community, notifications
from app.privacy import FaceBlurrer
from PIL import Image

from tests.factories import jpeg_bytes, noise_photo

LAT, LON = 10.7626, 106.6602
DEG_PER_M = 1 / 111_320
LARVAE = {"water_stagnant": "yes", "container_type": "flower_pot", "organic_waste": "no",
          "moving_organisms": "yes", "nearby_place": "far", "contact": "none", "recent_rain": "within_48h"}

VOLUNTEER = {"Authorization": "Bearer vol-token-123"}
EXPERT = {"Authorization": "Bearer exp-token-789"}


@pytest.fixture
def reviewers(monkeypatch):
    monkeypatch.setenv("AQUAPULSE_REVIEWERS", "volunteer:vol-01:vol-token-123,expert:exp-01:exp-token-789")


def observe(client, reporter="alice", seed=0, north_m=0.0, answers=None):
    response = client.post(
        "/observations",
        data={"latitude": str(LAT + north_m * DEG_PER_M), "longitude": str(LON), "reporter_id": reporter,
              "answers": json.dumps(LARVAE if answers is None else answers)},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=seed)), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def points(database, user):
    with database.connect() as conn:
        return community.profile(conn, user)["points"]


# --- points (section 19) -----------------------------------------------------------------

def test_a_report_earns_points_once_and_duplicates_earn_none(client_with_database, database):
    first = observe(client_with_database, seed=1)
    assert first["points_awarded"] == 10
    again = observe(client_with_database, seed=1)  # the same photo, same place
    assert again["duplicate_of"] == first["id"]
    assert again["points_awarded"] == 0
    assert points(database, "alice") == 10


def test_sending_many_photos_stops_paying(client_with_database, database):
    awarded = [observe(client_with_database, seed=100 + i, north_m=i * 400)["points_awarded"]
               for i in range(community.DAILY_REPORT_AWARDS + 1)]
    assert awarded == [10] * community.DAILY_REPORT_AWARDS + [0]


def test_verification_pays_the_reporter_and_the_checker(client_with_database, database, reviewers):
    task = observe(client_with_database, seed=2)["verification_task_id"]
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER, json={"verdict": "confirmed"})
    assert points(database, "alice") == 10 + 20
    assert points(database, "vol-01") == 5

    personal = client_with_database.get("/notifications", params={"reporter_id": "alice"}).json()["personal"]
    assert [n["kind"] for n in personal] == ["verification_result"]
    assert "đã được xác minh" in personal[0]["message"]


def test_leaderboard_hides_ids_and_profile_lists_badges(client_with_database, database):
    observe(client_with_database, reporter="reporter-anna", seed=3)
    leaders = client_with_database.get("/community/leaderboard").json()["leaders"]
    assert leaders == [{"user": "re…nna", "points": 10}]
    profile = client_with_database.get("/community/profile/reporter-anna").json()
    assert {b["name"] for b in profile["badges"]} == {
        "Water Watcher", "Vector Scout", "Community Verifier", "River Guardian", "Post-Rain Responder"}
    assert not any(b["earned"] for b in profile["badges"])


def test_leaderboard_demo_participants_require_opt_in(client_with_database, database):
    with database.connect() as conn:
        community.award(conn, "demo-local-vol-01", "task_completed", "demo-local-mission")
        community.award(conn, "alice", "peer_check", "real-check")
    real = client_with_database.get("/community/leaderboard").json()["leaders"]
    assert real == [{"user": community.mask("alice"), "points": 5}]
    demo = client_with_database.get("/community/leaderboard?include_demo=true").json()["leaders"]
    assert demo == [{"user": community.mask("demo-local-vol-01"), "points": 30}, *real]


# --- alerts and notifications (sections 17, 20) ------------------------------------------

def three_reports(client):
    return [observe(client, reporter=r, seed=10 + i, north_m=i * 40) for i, r in enumerate(("r1", "r2", "r3"))]


def test_a_hotspot_opens_one_alert_and_a_calm_notice(client_with_database, database):
    reports = three_reports(client_with_database)
    assert reports[-1]["alert_changes"][0]["change"] == "opened"
    listed = client_with_database.get("/alerts").json()["alerts"]
    assert len(listed) == 1 and listed[0]["reports"] == 3 and listed[0]["status"] == "open"

    observe(client_with_database, reporter="r4", seed=14, north_m=120)  # the same place grows
    listed = client_with_database.get("/alerts").json()["alerts"]
    assert len(listed) == 1 and listed[0]["reports"] == 4

    area = client_with_database.get("/notifications", params={"latitude": LAT, "longitude": LON}).json()["area"]
    opened = [n for n in area if n["kind"] == "alert_opened"]
    assert len(opened) == 1
    message = opened[0]["message"]
    assert "chưa kết luận có muỗi truyền bệnh" in message
    assert "ổ dịch" not in message.lower()


def test_rising_level_escalates_the_alert(client_with_database, database):
    three_reports(client_with_database)
    level = client_with_database.get("/alerts").json()["alerts"][0]["level"]
    assert level != "red"
    with database.connect() as conn:
        conn.execute("UPDATE observations SET level = 'red'")
        changes = alerts.refresh(conn)
    assert [c["change"] for c in changes] == ["escalated"]
    kinds = [n["kind"] for n in client_with_database.get(
        "/notifications", params={"latitude": LAT, "longitude": LON}).json()["area"]]
    assert "alert_escalated" in kinds


def test_only_an_expert_closes_an_alert(client_with_database, database, reviewers):
    three_reports(client_with_database)
    alert = client_with_database.get("/alerts").json()["alerts"][0]["id"]
    assert client_with_database.post(f"/alerts/{alert}/verify", headers=VOLUNTEER,
                                     json={"verdict": "resolved"}).status_code == 403
    done = client_with_database.post(f"/alerts/{alert}/verify", headers=EXPERT,
                                     json={"verdict": "resolved", "note": "Đã dọn chậu."})
    assert done.json()["status"] == "resolved"
    assert client_with_database.post(f"/alerts/{alert}/verify", headers=EXPERT,
                                     json={"verdict": "dismissed"}).status_code == 409
    kinds = [n["kind"] for n in client_with_database.get(
        "/notifications", params={"latitude": LAT, "longitude": LON}).json()["area"]]
    assert "alert_resolved" in kinds


def test_outbreak_wording_is_never_stored(database):
    with database.connect() as conn, pytest.raises(notifications.UnsafeMessage):
        notifications._store(conn, "test", "Ổ dịch sốt xuất huyết đã xuất hiện tại phường 5",
                             latitude=LAT, longitude=LON)


# --- community tasks (section 19) -----------------------------------------------------------

MISSION = {"title": "Kiểm tra 3 điểm nước đọng sau mưa", "latitude": LAT, "longitude": LON,
           "radius_m": 500, "target_count": 1, "reward_points": 100, "hours": 24}


def test_mission_completes_only_with_after_photos(client_with_database, database, reviewers):
    assert client_with_database.post("/tasks", headers=VOLUNTEER, json=MISSION).status_code == 403
    mission = client_with_database.post("/tasks", headers=EXPERT, json=MISSION).json()["id"]
    assert client_with_database.get("/tasks").json()["tasks"][0]["title"] == MISSION["title"]
    assert client_with_database.post(f"/tasks/{mission}/complete", headers=VOLUNTEER).status_code == 409

    task = observe(client_with_database, seed=20)["verification_task_id"]
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    after = client_with_database.post(
        f"/verification/tasks/{task}/photos", headers=VOLUNTEER,
        data={"kind": "after", "answers": json.dumps({"water_stagnant": "no"})},
        files={"image": ("b.jpg", jpeg_bytes(noise_photo(seed=21)), "image/jpeg")})
    assert after.status_code == 201, after.text

    done = client_with_database.post(f"/tasks/{mission}/complete", headers=VOLUNTEER).json()
    assert done["status"] == "completed" and done["points"] == 100
    assert points(database, "vol-01") == 15 + 100  # after-photo + mission
    assert client_with_database.post(f"/tasks/{mission}/complete", headers=VOLUNTEER).status_code == 409


# --- public views (sections 17, 18, 22) -----------------------------------------------------

def test_map_points_are_coarse_and_anonymous(client_with_database, database):
    three_reports(client_with_database)
    body = client_with_database.get("/map/points").json()
    assert len(body["features"]) == 3
    for feature in body["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        assert round(lat, 3) == lat and round(lon, 3) == lon
        props = feature["properties"]
        assert "reporter_id" not in props
        assert props["nearby_reports"] == 2
        assert {"type", "observed_at", "level", "color", "confidence", "status_label"} <= props.keys()


def test_observation_detail_has_no_reporter_and_photo_needs_login(client_with_database, reviewers):
    report = observe(client_with_database, seed=30)
    detail = client_with_database.get(f"/observations/{report['id']}").json()
    assert "reporter_id" not in detail and "image_path" not in detail
    assert detail["latitude"] == round(LAT, 3)
    assert client_with_database.get(f"/observations/{report['id']}/photo").status_code == 401
    assert client_with_database.get(f"/observations/{report['id']}/photo", headers=EXPERT).status_code == 200
    missing = "00000000-0000-0000-0000-000000000000"
    assert client_with_database.get(f"/observations/{missing}").status_code == 404


def test_marking_ai_output_wrong_sends_the_report_to_review(client_with_database, reviewers):
    report = observe(client_with_database, seed=31, answers={})
    assert report["verification_task_id"] is None
    bad = client_with_database.post(f"/observations/{report['id']}/feedback", json={"wrong_items": ["magic"]})
    assert bad.status_code == 422
    body = client_with_database.post(f"/observations/{report['id']}/feedback",
                                     json={"reporter_id": "alice", "wrong_items": ["water"]}).json()
    assert body["verification_task_id"] is not None
    tasks = client_with_database.get("/verification/tasks", headers=EXPERT).json()["tasks"]
    assert "kết quả AI sai" in tasks[0]["reasons"][0]


def test_reanalysis_is_for_reviewers(client_with_database, reviewers):
    report = observe(client_with_database, seed=32)
    assert client_with_database.post(f"/observations/{report['id']}/analyze").status_code == 401
    again = client_with_database.post(f"/observations/{report['id']}/analyze", headers=EXPERT)
    assert again.status_code == 200
    assert again.json()["assessment"]["risk"] == report["assessment"]["risk"]


# --- metrics (section 21) ------------------------------------------------------------------

def test_metrics_follow_the_plan_formulas(client_with_database, database, reviewers):
    task = observe(client_with_database, seed=40)["verification_task_id"]
    observe(client_with_database, reporter="bob", seed=41, north_m=2000)
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER, json={"verdict": "confirmed"})
    client_with_database.post(
        f"/verification/tasks/{task}/photos", headers=VOLUNTEER,
        data={"kind": "after", "answers": json.dumps({"water_stagnant": "no"})},
        files={"image": ("b.jpg", jpeg_bytes(noise_photo(seed=42)), "image/jpeg")})

    m = client_with_database.get("/dashboard/metrics").json()
    assert m["total_observations"] == 2
    assert m["observations_today"] == 2
    assert m["verified_observations"] == 1
    assert m["verification_rate"] == 0.5
    assert m["reports_after_rainfall"] == 2
    assert m["average_response_hours"] is not None
    assert m["treated_sites"] == 1
    assert m["risk_after"] < m["risk_before"]
    assert m["risk_reduction_pct"] > 0
    assert sum(d["reports"] for d in m["daily"]) == 2


# --- privacy (section 22) -------------------------------------------------------------------

class OneFace:
    """Stands in for YuNet: always finds one face in the middle of the picture."""

    def setInputSize(self, size):
        self.size = size

    def detect(self, image):
        h, w = image.shape[:2]
        return 1, np.array([[w * 0.4, h * 0.4, w * 0.2, h * 0.2]], dtype=np.float32)


def test_faces_are_blurred_and_the_rest_is_untouched():
    photo = noise_photo(size=(400, 300), seed=5)
    blurred, count = FaceBlurrer(detector=OneFace()).blur(photo)
    assert count == 1
    before, after = np.asarray(photo).astype(int), np.asarray(blurred).astype(int)
    face = (slice(125, 175), slice(165, 235))
    assert after[face].std() < before[face].std() / 2  # the noise inside the face box is gone
    assert (before[:40, :40] == after[:40, :40]).all()  # far from the face: unchanged


def test_no_face_means_no_change():
    class NoFace(OneFace):
        def detect(self, image):
            return 1, None

    photo = Image.new("RGB", (200, 200), (10, 120, 200))
    same, count = FaceBlurrer(detector=NoFace()).blur(photo)
    assert count == 0 and same is photo


# --- backend failure cases (section 22) ---------------------------------------------------

def test_report_without_gps_is_refused(client_with_database):
    response = client_with_database.post(
        "/observations", data={"reporter_id": "alice"},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=50)), "image/jpeg")})
    assert response.status_code == 422


def test_oversized_photo_is_refused(client_with_database, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1000)
    response = client_with_database.post(
        "/observations", data={"latitude": str(LAT), "longitude": str(LON)},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=51)), "image/jpeg")})
    assert response.status_code == 413


def test_unknown_observation_type_is_refused(client_with_database):
    response = client_with_database.post(
        "/observations", data={"latitude": str(LAT), "longitude": str(LON),
                               "answers": json.dumps({"observation_group": "alien_eggs"})},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=52)), "image/jpeg")})
    assert response.status_code == 422


class DownVision:
    provider, model, sends_photo_off_device = "qwen", "down", False

    def analyze(self, image, lang="vi"):
        from app.vision import VisionError
        raise VisionError("Qwen không phản hồi")


def test_report_is_still_stored_when_the_vision_model_is_down(client_with_database):
    from app.main import app
    app.state.vision = DownVision()
    response = client_with_database.post(
        "/observations?with_vision=true", data={"latitude": str(LAT), "longitude": str(LON), "reporter_id": "alice"},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=53)), "image/jpeg")})
    assert response.status_code == 201
    assert "Qwen" in response.json()["vision"]["error"]
