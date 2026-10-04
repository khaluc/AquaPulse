"""Scenarios from sections 11 and 12 of the plan, run through fusion and the risk engine."""

import pytest
from app.domain import find_out_of_scope_claims
from app.features import Feature, FeatureSet
from app.fusion import ReportAnswers, fuse
from app.risk import RECOMMENDATIONS, assess
from app.vision import Signal, VisionAnalysis


def features(containers=None, water=None):
    """containers: {class: confidence}; water: best in-container water confidence, or None."""
    return FeatureSet(
        features={name: Feature(conf, 1, 0.05) for name, conf in (containers or {}).items()},
        water_area_fraction=None if water is None else (0.1 if water else 0.0),
        water_confidence=water,
    )


def vision(**detected):
    """detected: {signal: certainty}; every other signal is 'not seen, medium'."""
    names = ("standing_water", "artificial_container", "organic_waste", "oil_sheen",
             "foam", "mosquito_larvae", "fly_cluster")
    signals = {n: Signal(n in detected, detected.get(n, "medium")) for n in names}
    reasons = tuple(n for n in ("oil_sheen", "foam", "mosquito_larvae", "fly_cluster") if n in detected)
    return VisionAnalysis(signals, bool(reasons), "", "", "qwen", "test", 0.0, review_reasons=reasons)


def run(feats, answers=None, vis=None):
    answers = ReportAnswers(**(answers or {}))
    fusion = fuse(feats, answers, vis)
    return fusion, assess(fusion, answers, vis)


def test_plan_conflict_example_asks_the_reporter_and_does_not_raise_the_alert():
    """Section 11: reporter says no water, the detector sees 0.82, the vision model 0.79."""
    fusion, risk = run(
        features({"used_tire": 0.9}, water=0.82),
        {"water_stagnant": "no", "container_type": "used_tire", "nearby_place": "school",
         "contact": "children_nearby", "recent_rain": "within_48h", "organic_waste": "no"},
        vision(standing_water="high", artificial_container="high"),
    )
    assert [c.signal for c in fusion.conflicts] == ["standing_water"]
    assert risk.needs_reporter_confirmation is True
    assert risk.level in ("green", "yellow")  # never orange/red on its own
    assert risk.needs_verification is True


def test_low_confidence_does_not_downgrade_a_real_risk():
    """The plan's R = C x (...) turns this orange report green when C = 0.5."""
    _, risk = run(
        features({"used_tire": 0.9}, water=0.8),
        {"water_stagnant": "yes", "container_type": "used_tire", "organic_waste": "no",
         "nearby_place": "school", "recent_rain": "none", "contact": "children_nearby"},
    )
    assert risk.risk == pytest.approx(0.555, abs=0.01)  # E0 V0.9 P0.9 W0.2 H0.8
    assert risk.level == "orange"
    assert risk.as_dict()["risk_times_confidence"] < risk.risk


def test_reliability_changes_the_weight_of_the_answer_not_its_meaning():
    ai_sees_water = features(water=0.8)
    new, _ = run(ai_sees_water, {"water_stagnant": "no", "reporter_level": "new"})
    volunteer, _ = run(ai_sees_water, {"water_stagnant": "no", "reporter_level": "volunteer"})
    # A more reliable "no" pulls the probability of water further down.
    assert volunteer.signals["standing_water"].probability < new.signals["standing_water"].probability
    yes, _ = run(ai_sees_water, {"water_stagnant": "yes", "reporter_level": "volunteer"})
    assert yes.signals["standing_water"].probability > volunteer.signals["standing_water"].probability


def test_unknown_weather_is_left_out_not_scored_as_dry():
    _, risk = run(features({"plant_pot": 0.8}, water=0.7),
                  {"nearby_place": "home", "contact": "passing", "organic_waste": "no"})
    assert risk.components["W"].value is None
    assert "Thời tiết, mưa" in risk.missing
    # E0, V0.8 (water in a pot), P0.6, H0.4, renormalised without W (weights sum 0.85)
    expected = (0.25 * 0 + 0.30 * 0.8 + 0.15 * 0.6 + 0.15 * 0.4) / 0.85
    assert risk.risk == pytest.approx(expected, abs=1e-6)


def test_larvae_report_scores_top_vector_risk_and_forces_verification():
    _, risk = run(features(), {"moving_organisms": "yes", "reporter_level": "trusted"})
    assert risk.components["V"].value == 1.0
    assert risk.needs_verification is True
    assert any("ấu trùng" in r for r in risk.verification_reasons)


def test_vision_alone_never_raises_the_score():
    """Qwen claimed oil sheen on clean water; that alone must not make a report red."""
    fusion, risk = run(features(), vis=vision(oil_sheen="high"))
    assert fusion.unconfirmed == ["oil_sheen"]
    assert risk.components["E"].value == 0.0
    assert risk.needs_verification is True
    assert any("chưa tính vào điểm" in r for r in risk.verification_reasons)
    assert not any("môi trường" in r for r in risk.recommendations)


def test_reporter_confirming_what_the_vision_model_saw_counts():
    fusion, risk = run(features(), {"observation_types": ["oil_sheen"]}, vision(oil_sheen="high"))
    assert fusion.signals["oil_sheen"].present is True
    assert fusion.unconfirmed == []
    assert risk.components["E"].value == pytest.approx(0.9)


def test_detector_alone_finding_nothing_is_green():
    fusion, risk = run(features())
    assert risk.components["V"].value == 0.0
    assert risk.level == "green"
    assert "reporter" not in fusion.sources_used


def test_tyre_seen_only_by_the_detector_is_flagged_as_unvalidated():
    _, risk = run(features({"used_tire": 0.9}, water=0.8), {"nearby_place": "far"})
    assert risk.components["V"].value == pytest.approx(0.9)
    assert any("lốp xe chưa được kiểm chứng" in r for r in risk.verification_reasons)


def test_confidence_rises_when_sources_agree():
    agree, _ = run(features({"plant_pot": 0.85}, water=0.8),
                   {"water_stagnant": "yes", "container_type": "flower_pot"},
                   vision(standing_water="high", artificial_container="high"))
    disagree, _ = run(features({"plant_pot": 0.85}, water=0.8),
                      {"water_stagnant": "no", "container_type": "none"},
                      vision(standing_water="high", artificial_container="high"))
    assert agree.confidence > disagree.confidence
    assert agree.confidence_parts["coverage"] == 1.0


def test_every_recommendation_stays_in_scope():
    for text in RECOMMENDATIONS.values():
        assert find_out_of_scope_claims(text) == [], text


def test_unknown_observation_type_is_rejected():
    with pytest.raises(ValueError):
        ReportAnswers(observation_types=["alien"])


def test_photo_alone_cannot_raise_orange_or_red():
    """Found on the demo page: one pot of water and no answers scored R = V = 0.8, red."""
    _, risk = run(features({"plant_pot": 0.8}, water=0.8))
    assert risk.components["V"].value == pytest.approx(0.8)
    assert risk.known_weight == pytest.approx(0.30)
    assert risk.level == "yellow"
    assert risk.capped_by_missing_data is True
    assert risk.needs_reporter_confirmation is True
    assert "gần khu dân cư" in risk.action


def test_enough_answers_lift_the_cap():
    _, risk = run(features({"plant_pot": 0.8}, water=0.8),
                  {"organic_waste": "no", "nearby_place": "school", "contact": "children_nearby"})
    assert risk.known_weight >= 0.7
    assert risk.capped_by_missing_data is False
    assert risk.level in ("orange", "red")
