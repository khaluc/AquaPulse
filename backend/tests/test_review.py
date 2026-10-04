"""Section 16: routing a report to the reporter, a volunteer or an expert."""

import json

import pytest
from app.features import Feature, FeatureSet
from app.fusion import ReportAnswers
from app.pipeline import score
from app.vision import Signal, VisionAnalysis

from tests.factories import jpeg_bytes, noise_photo

NAMES = ("standing_water", "artificial_container", "organic_waste", "oil_sheen",
         "foam", "mosquito_larvae", "fly_cluster")
FULL_ANSWERS = {"water_stagnant": "yes", "container_type": "flower_pot", "organic_waste": "no",
                "moving_organisms": "no", "nearby_place": "far", "contact": "none", "recent_rain": "none"}


def vision(**seen):
    signals = {n: Signal(n in seen, seen.get(n, "high")) for n in NAMES}
    return VisionAnalysis(signals, False, "", "", "qwen", "t", 0.0)


def pot_with_water():
    return FeatureSet({"plant_pot": Feature(0.9, 1, 0.05)}, 0.1, 0.85)


def route_for(answers=None, vis=None, features=None, vision_expected=None):
    answers = ReportAnswers(**(answers or {}))
    expected = vis is not None if vision_expected is None else vision_expected
    return score(features or pot_with_water(), answers, vis, 0, expected)[:3]


# --- routing ------------------------------------------------------------------------

def test_agreeing_sources_without_serious_signs_are_shown():
    fusion, _, review = route_for(FULL_ANSWERS)
    # Before the coverage fix the best possible C without the vision model was 0.833,
    # so the "show" branch of section 16 could never happen.
    assert fusion.confidence > 0.85
    assert review.decision == "show"
    assert review.status == "published"


def test_oil_sheen_is_verified_whatever_the_confidence():
    """The plan's chart only checks serious signs on the C > 0.85 branch."""
    _, _, review = route_for({**FULL_ANSWERS, "observation_types": ["oil_sheen"]})
    assert review.decision == "verify"
    assert review.expert_required
    assert "Váng dầu." in review.reasons


def test_chemical_smell_and_dead_animal_need_an_expert():
    _, _, chemical = route_for({**FULL_ANSWERS, "odor": "chemical"})
    _, _, animal = route_for({**FULL_ANSWERS, "observation_types": ["dead_animal"]})
    for review in (chemical, animal):
        assert review.decision == "verify"
        assert review.expert_required


def test_suspected_larvae_go_to_a_volunteer():
    _, _, review = route_for({**FULL_ANSWERS, "moving_organisms": "yes"})
    assert review.decision == "verify"
    assert "Nghi ngờ lăng quăng." in review.reasons


def test_photo_without_answers_asks_the_reporter():
    fusion, _, review = route_for()
    assert 0.6 <= fusion.confidence <= 0.85
    assert review.decision == "confirm"
    assert review.ask_reporter


def test_models_disagreeing_needs_a_person():
    """Detector sees a pot at 0.9; the vision model says, with high certainty, there is none."""
    fusion, _, review = route_for(FULL_ANSWERS, vision(standing_water="high"))
    assert [c.signal for c in fusion.model_conflicts] == ["artificial_container"]
    assert review.decision == "verify"
    assert any("Hai model mâu thuẫn" in r for r in review.reasons)


def test_low_confidence_goes_to_the_queue():
    """The reporter contradicts both models on both signals."""
    answers = {**FULL_ANSWERS, "water_stagnant": "no", "container_type": "none"}
    fusion, _, review = route_for(answers, vision(standing_water="high", artificial_container="high"))
    assert fusion.confidence < 0.6
    assert review.decision == "verify"


# --- the reporter confirms (steps D-H-I) -------------------------------------------------

def _observe(client, reporter="alice", answers=None, photo_seed=0):
    return client.post(
        "/observations",
        data={"latitude": "10.7626", "longitude": "106.6602", "reporter_id": reporter,
              "answers": json.dumps(answers or {})},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=photo_seed)), "image/jpeg")},
    ).json()


def test_reporter_confirmation_rescores_and_reroutes(client_with_database):
    first = _observe(client_with_database)
    assert first["status"] == "needs_confirmation"

    confirmed = client_with_database.post(
        f"/observations/{first['id']}/confirm",
        data={"reporter_id": "alice", "answers": json.dumps({**FULL_ANSWERS, "odor": "chemical"})},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "needs_verification"      # the correction changed the route
    assert body["verification_task_id"] is not None
    assert body["answers"]["odor"] == "chemical"


def test_only_the_reporter_can_confirm(client_with_database):
    report = _observe(client_with_database)
    wrong = client_with_database.post(f"/observations/{report['id']}/confirm",
                                      data={"reporter_id": "mallory", "answers": "{}"})
    assert wrong.status_code == 403


def test_self_declared_reporter_level_is_ignored(client_with_database):
    body = _observe(client_with_database, answers={"reporter_level": "volunteer"})
    assert body["answers"]["reporter_level"] == "new"


# --- the verification queue (steps E-J-K-L) ----------------------------------------------

VOLUNTEER = {"Authorization": "Bearer vol-token-123"}
VOLUNTEER_B = {"Authorization": "Bearer vol-token-456"}
EXPERT = {"Authorization": "Bearer exp-token-789"}


@pytest.fixture
def reviewers(monkeypatch):
    monkeypatch.setenv("AQUAPULSE_REVIEWERS",
                       "volunteer:vol-01:vol-token-123,volunteer:vol-02:vol-token-456,expert:exp-01:exp-token-789")


def _queued(client, reporter="alice", answers=None, seed=0):
    body = _observe(client, reporter, answers or {**FULL_ANSWERS, "moving_organisms": "yes"}, seed)
    assert body["status"] == "needs_verification", body.get("review")
    return body


def test_volunteer_confirms_a_simple_case(client_with_database, reviewers):
    report = _queued(client_with_database)
    task = report["verification_task_id"]
    listed = client_with_database.get("/verification/tasks", headers=VOLUNTEER).json()["tasks"]
    assert [t["id"] for t in listed] == [task]

    assert client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER).status_code == 200
    done = client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER,
                                     json={"verdict": "confirmed", "note": "Thấy lăng quăng trong chậu."}).json()
    assert done == {"id": task, "status": "resolved", "final_verdict": "confirmed"}
    observations = client_with_database.get("/observations").json()["observations"]
    assert observations[0]["status"] == "verified"


def test_expert_case_is_escalated_after_the_volunteer(client_with_database, reviewers):
    report = _queued(client_with_database, answers={**FULL_ANSWERS, "odor": "chemical"})
    task = report["verification_task_id"]
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    submitted = client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER,
                                          json={"verdict": "confirmed"}).json()
    assert submitted["status"] == "escalated"

    # A volunteer cannot give the final word; the expert can.
    assert client_with_database.post(f"/verification/tasks/{task}/resolve", headers=VOLUNTEER_B,
                                     json={"verdict": "confirmed"}).status_code == 403
    final = client_with_database.post(f"/verification/tasks/{task}/resolve", headers=EXPERT,
                                      json={"verdict": "not_confirmed", "note": "Mùi từ thùng sơn, đã dọn."}).json()
    assert final["final_verdict"] == "not_confirmed"

    trail = client_with_database.get(f"/verification/tasks/{task}/events", headers=EXPERT).json()["events"]
    assert [e["action"] for e in trail] == [
        "queued", "claimed", "submitted:confirmed", "escalated", "resolved:not_confirmed"]
    assert trail[-1]["actor_id"] == "exp-01"


def test_unclear_verdict_goes_to_an_expert(client_with_database, reviewers):
    task = _queued(client_with_database)["verification_task_id"]
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    body = client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER,
                                     json={"verdict": "unclear"}).json()
    assert body["status"] == "escalated"


def test_nobody_verifies_their_own_report(client_with_database, reviewers):
    task = _queued(client_with_database, reporter="vol-01")["verification_task_id"]
    assert client_with_database.get("/verification/tasks", headers=VOLUNTEER).json()["tasks"] == []
    assert client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER).status_code == 403
    # Another volunteer can.
    assert client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER_B).status_code == 200


def test_only_the_claimer_submits(client_with_database, reviewers):
    task = _queued(client_with_database)["verification_task_id"]
    client_with_database.post(f"/verification/tasks/{task}/claim", headers=VOLUNTEER)
    other = client_with_database.post(f"/verification/tasks/{task}/submit", headers=VOLUNTEER_B,
                                      json={"verdict": "confirmed"})
    assert other.status_code == 409


def test_dismissed_reports_leave_the_hotspots(client_with_database, database, reviewers):
    for i, reporter in enumerate(("r1", "r2", "r3")):
        _queued(client_with_database, reporter=reporter, seed=i + 10)
    assert len(client_with_database.get("/hotspots").json()["hotspots"]) == 1

    first = client_with_database.get("/verification/tasks", headers=EXPERT).json()["tasks"][0]["id"]
    client_with_database.post(f"/verification/tasks/{first}/resolve", headers=EXPERT,
                              json={"verdict": "not_confirmed"})
    assert client_with_database.get("/hotspots").json()["hotspots"] == []  # only 2 reports left


def test_verified_reports_make_a_reporter_trusted(client_with_database, reviewers):
    for seed in range(3):
        task = _queued(client_with_database, reporter="bob", seed=seed + 20)["verification_task_id"]
        client_with_database.post(f"/verification/tasks/{task}/resolve", headers=EXPERT,
                                  json={"verdict": "confirmed"})
    assert _observe(client_with_database, reporter="bob", photo_seed=99)["answers"]["reporter_level"] == "trusted"


def test_queue_needs_a_login(client_with_database, monkeypatch):
    monkeypatch.delenv("AQUAPULSE_REVIEWERS", raising=False)
    assert client_with_database.get("/verification/tasks").status_code == 503
    monkeypatch.setenv("AQUAPULSE_REVIEWERS", "volunteer:vol-01:vol-token-123")
    assert client_with_database.get("/verification/tasks").status_code == 401
    assert client_with_database.get("/verification/tasks",
                                    headers={"Authorization": "Bearer wrong-token"}).status_code == 401
