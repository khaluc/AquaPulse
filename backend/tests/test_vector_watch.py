"""The Vector Watch module: catalog, group rules, routing, storage, dashboard, before/after."""

import json

import pytest
from app.domain import find_out_of_scope_claims
from app.features import Feature, FeatureSet
from app.fusion import ObservationGroup, ReportAnswers, fuse
from app.pipeline import score
from app.vector_watch import (
    AEDES_DRY_CAP,
    CATALOG,
    QUESTIONS,
    aedes_score,
    catalog,
    culex_score,
    fly_score,
    water_signal_score,
)
from app.vision import Signal, VisionAnalysis

from tests.factories import jpeg_bytes, noise_photo

G = ObservationGroup
NAMES = ("standing_water", "artificial_container", "organic_waste", "oil_sheen",
         "foam", "mosquito_larvae", "fly_cluster")


def features(containers=None, water=0.85):
    return FeatureSet({n: Feature(c, 1, 0.05) for n, c in (containers or {"plant_pot": 0.9}).items()},
                      0.1 if water else 0.0, water)


def fused(answers, feats=None, vision=None):
    answers = ReportAnswers(**answers)
    return fuse(feats or features(), answers, vision), answers


def vision(**seen):
    return VisionAnalysis({n: Signal(n in seen, seen.get(n, "high")) for n in NAMES}, False, "", "", "qwen", "t", 0)


# --- catalog ------------------------------------------------------------------------

def test_catalog_has_three_tiers():
    tiers = [spec.tier for spec in CATALOG.values()]
    assert (tiers.count("A"), tiers.count("B"), tiers.count("C")) == (5, 4, 1)  # A includes river_health
    body = catalog()
    assert len(body["tier_c_examples"]) == 6
    assert set(body["layers"]) == {"mosquito_breeding", "fly_organic", "water_anomaly", "verified"}


def test_every_group_question_exists_and_every_text_stays_in_scope():
    for spec in CATALOG.values():
        for field in spec.questions:
            assert field in QUESTIONS, (spec.id, field)
            assert field in ReportAnswers.model_fields, field
        for text in (spec.positive, spec.negative, spec.limitation):
            assert find_out_of_scope_claims(text) == [], text


# --- group rules --------------------------------------------------------------------

def test_aedes_rule_uses_the_brief_weights():
    fusion, answers = fused({"water_stagnant": "yes", "container_type": "flower_pot", "organic_waste": "no",
                             "recent_rain": "within_48h", "nearby_place": "school"})
    result = aedes_score(fusion, answers)
    parts = result.parts
    expected = (0.35 * parts["standing_water"] + 0.25 * parts["artificial_container"]
                + 0.15 * parts["organic_waste"] + 0.15 * 0.7 + 0.10 * 0.9)
    assert result.value == pytest.approx(expected)
    assert result.known_weight == pytest.approx(1.0)


def test_tyre_with_water_adds_the_bonus_and_is_capped_at_one():
    fusion, answers = fused({"water_stagnant": "yes", "container_type": "used_tire", "organic_waste": "yes",
                             "recent_rain": "flood_or_heavy", "nearby_place": "school"},
                            features({"used_tire": 0.9}))
    result = aedes_score(fusion, answers)
    assert result.value == pytest.approx(1.0)
    assert any("lốp xe" in n for n in result.notes)


def test_unknown_factors_are_left_out_not_zero():
    fusion, answers = fused({"water_stagnant": "yes", "organic_waste": "no"})
    result = aedes_score(fusion, answers)
    assert result.parts["recent_rain"] is None
    assert result.known_weight == pytest.approx(0.75)
    fusion_zero, answers_zero = fused({"water_stagnant": "yes", "organic_waste": "no",
                                       "recent_rain": "none", "nearby_place": "far"})
    assert result.value > aedes_score(fusion_zero, answers_zero).value


def test_no_standing_water_caps_aedes():
    """Found in the demo: the brief's sum still gave 0.61 after the water was poured out."""
    fusion, answers = fused({"water_stagnant": "no", "container_type": "flower_pot", "organic_waste": "yes",
                             "recent_rain": "flood_or_heavy", "nearby_place": "school"},
                            features(water=0.0))
    assert aedes_score(fusion, answers).value == pytest.approx(AEDES_DRY_CAP)


def test_culex_counts_repeated_reports_and_drain_inlets():
    answers = {"water_stagnant": "yes", "odor": "sewage", "organic_waste": "yes"}
    fusion, parsed = fused(answers, features({"drain_inlet": 0.9}))
    once = culex_score(fusion, parsed, features({"drain_inlet": 0.9}), nearby_reports=0)
    thrice = culex_score(fusion, parsed, features({"drain_inlet": 0.9}), nearby_reports=3)
    assert once.parts["drainage_problem"] == 1.0
    assert thrice.value > once.value
    assert culex_score(fusion, parsed, features(), nearby_reports=None).parts["repeated_reports"] is None


def test_fly_rule():
    fusion, answers = fused({"observation_group": "fly_cluster", "density": "many", "organic_waste": "yes",
                             "dead_animal_or_feces": "no", "odor": "rotten"})
    result = fly_score(fusion, answers)
    assert result.parts["fly_cluster"] == pytest.approx(1.0)
    assert result.value == pytest.approx(0.35 + 0.30 + 0.20 * result.parts["dead_animal_or_fecal_waste"] + 0.15)


def test_water_signal_uses_colour_foam_and_sheen():
    fusion, answers = fused({"water_color": "rainbow_sheen", "foam": "yes", "odor": "chemical"})
    result = water_signal_score(fusion, answers)
    assert result.parts["unusual_color"] == 1.0
    assert result.parts["oil_sheen"] == pytest.approx(1.0)  # rainbow sheen is a reporter vote for oil
    unsure, answers_unsure = fused({"water_color": "unsure"})
    assert water_signal_score(unsure, answers_unsure).parts["unusual_color"] is None


def test_vision_alone_does_not_raise_a_group_score():
    fusion, answers = fused({}, vision=vision(oil_sheen="high", foam="high"))
    result = water_signal_score(fusion, answers)
    assert result.parts["oil_sheen"] == 0.0
    assert result.parts["foam"] == 0.0


def test_group_score_is_not_multiplied_by_confidence():
    base = {"water_stagnant": "yes", "container_type": "flower_pot", "organic_waste": "no",
            "recent_rain": "within_48h", "nearby_place": "school"}
    new = score(features(), ReportAnswers(**base), None, 0, False)[3]
    volunteer = score(features(), ReportAnswers(**base, reporter_level="volunteer"), None, 0, False)[3]
    assert abs(new.group_score - volunteer.group_score) < 0.05  # reliability moves votes, not the scale


# --- routing by group -----------------------------------------------------------------

def _route(answers):
    return score(features(), ReportAnswers(**answers), None, 0, False)[2]


def test_mosquito_reports_always_need_a_person():
    review = _route({"observation_group": "mosquito_activity", "insect_seen": "adult_mosquito",
                     "density": "few", "nearby_place": "far", "contact": "none", "recent_rain": "none"})
    assert review.decision == "verify"
    assert not review.expert_required


def test_unusual_water_goes_to_an_expert_for_sampling():
    review = _route({"observation_group": "water_quality_signal", "water_color": "brown_black",
                     "foam": "yes", "odor": "sewage"})
    assert review.decision == "verify"
    assert review.expert_required
    assert any("lấy mẫu" in r for r in review.reasons)


def test_tier_c_is_recorded_for_an_expert():
    review = _route({"observation_group": "other_reference"})
    assert review.decision == "verify" and review.expert_required


# --- storage, dashboard, before/after ---------------------------------------------------

def _observe(client, answers, reporter="alice", seed=0, lat="10.7626"):
    return client.post(
        "/observations",
        data={"latitude": lat, "longitude": "106.6602", "reporter_id": reporter, "answers": json.dumps(answers)},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=seed)), "image/jpeg")},
    ).json()


AEDES = {"observation_group": "aedes_breeding_risk", "water_stagnant": "yes", "container_type": "flower_pot",
         "organic_waste": "no", "moving_organisms": "yes", "nearby_place": "home", "contact": "passing",
         "recent_rain": "within_48h"}


def test_stored_report_carries_domain_group_and_scores(client_with_database, database):
    body = _observe(client_with_database, AEDES)
    watch = body["vector_watch"]
    assert (watch["risk_domain"], watch["vector_group"]) == ("vector", "aedes_breeding_risk")
    with database.connect() as conn:
        row = conn.execute("SELECT risk_domain, vector_group, group_score, vector_breeding_risk, "
                           "human_contact_risk, categories FROM observations WHERE id = %s", (body["id"],)).fetchone()
    assert row["vector_group"] == "aedes_breeding_risk"
    assert row["group_score"] == pytest.approx(watch["group_score"], abs=1e-3)
    assert row["human_contact_risk"] == pytest.approx(0.4)
    assert "vector" in row["categories"]


def test_catalog_endpoint(client):
    body = client.get("/vector-watch/catalog").json()
    ids = {g["id"] for g in body["groups"]}
    assert "fly_cluster" in ids and "other_reference" in ids
    assert "nearby_place" in body["groups"][0]["questions"]


def test_dashboard_layers_and_table(client_with_database):
    _observe(client_with_database, AEDES, reporter="a", seed=1)
    _observe(client_with_database, {"observation_group": "fly_cluster", "density": "many",
                                    "organic_waste": "yes", "odor": "rotten"}, reporter="b", seed=2)
    _observe(client_with_database, {"observation_group": "water_quality_signal", "water_color": "brown_black",
                                    "foam": "yes", "odor": "sewage"}, reporter="c", seed=3)
    body = client_with_database.get("/dashboard/data").json()
    counts = {name: layer["count"] for name, layer in body["layers"].items()}
    assert counts == {"mosquito_breeding": 1, "fly_organic": 1, "water_anomaly": 1, "verified": 0}
    point = body["layers"]["mosquito_breeding"]["geojson"]["features"][0]["geometry"]["coordinates"]
    assert point == [106.6602, 10.7626]  # rounded to 4 decimals
    assert {row["status"] for row in body["table"]} >= {"Cần lấy mẫu"}


def test_dashboard_includes_reference_reports_without_risk_score(client_with_database, database):
    report = _observe(client_with_database, {"observation_group": "other_reference"})
    response = client_with_database.get("/dashboard/data")
    assert response.status_code == 200
    body = response.json()
    assert body["reports"] == 1
    assert all(layer["count"] == 0 for layer in body["layers"].values())
    assert body["table"][0]["id"] == report["id"]
    assert body["table"][0]["score"] is None

    with database.connect() as conn:
        conn.execute("UPDATE observations SET status = 'verified' WHERE id = %s", (report["id"],))
    verified = client_with_database.get("/dashboard/data").json()["layers"]["verified"]
    assert verified["count"] == 1
    assert verified["geojson"]["features"][0]["properties"]["score"] is None


REVIEWERS = "volunteer:vol-01:vol-token-123,volunteer:vol-02:vol-token-456,expert:exp-01:exp-token-789"


def test_after_photo_lowers_the_score_on_the_dashboard(client_with_database, monkeypatch):
    monkeypatch.setenv("AQUAPULSE_REVIEWERS", REVIEWERS)
    volunteer = {"Authorization": "Bearer vol-token-123"}
    report = _observe(client_with_database, AEDES)
    task = report["verification_task_id"]
    before = report["vector_watch"]["group_score"]

    other = {"Authorization": "Bearer vol-token-456"}
    photo = {"image": ("after.jpg", jpeg_bytes(noise_photo(seed=5)), "image/jpeg")}
    assert client_with_database.post(f"/verification/tasks/{task}/photos", headers=other,
                                     data={"kind": "after"}, files=photo).status_code == 403  # not claimed

    client_with_database.post(f"/verification/tasks/{task}/claim", headers=volunteer)
    after = client_with_database.post(
        f"/verification/tasks/{task}/photos", headers=volunteer,
        data={"kind": "after", "answers": json.dumps({"water_stagnant": "no"})}, files=photo,
    ).json()
    assert after["before_score"] == pytest.approx(before, abs=1e-3)
    # The fake water model still "sees" water, so the verifier's "no water" only halves
    # the water signal: the score drops, but not to the dry cap (tested separately).
    assert after["group_score"] < before

    client_with_database.post(f"/verification/tasks/{task}/submit", headers=volunteer,
                              json={"verdict": "confirmed", "note": "Đã đổ nước."})
    body = client_with_database.get("/dashboard/data").json()
    treated = body["layers"]["verified"]["geojson"]["features"][0]["properties"]
    assert treated["treated"] is True
    assert treated["current_score"] == pytest.approx(after["group_score"], abs=1e-3)
    events = client_with_database.get(f"/verification/tasks/{task}/events", headers=volunteer).json()["events"]
    assert "photo:after" in [e["action"] for e in events]
