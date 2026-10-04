import pytest
from app.detector import Detection
from app.features import MISSING_FEATURES, extract_features


def det(name, conf, box, class_id=0):
    return Detection(class_id, name, conf, box)


IMAGE = (1000, 1000)  # 1,000,000 px, so an area fraction of 0.01 is a 100x100 box


def test_keeps_count_not_just_max_confidence():
    found = extract_features(
        [det("plant_pot", 0.9, (0, 0, 100, 100)), det("plant_pot", 0.5, (500, 500, 600, 600))],
        IMAGE, threshold=0.35,
    )
    pot = found.features["plant_pot"]
    assert pot.max_confidence == pytest.approx(0.9)
    assert pot.count == 2
    assert pot.area_fraction == pytest.approx(0.02)


def test_detections_below_threshold_are_ignored():
    found = extract_features([det("used_tire", 0.2, (0, 0, 100, 100))], IMAGE, threshold=0.35)
    assert found.features == {}
    assert found.confidence("used_tire") == 0.0
    assert found.count("used_tire") == 0


def test_overlapping_boxes_are_not_counted_twice():
    found = extract_features(
        [det("plant_pot", 0.9, (0, 0, 200, 200)), det("plant_pot", 0.8, (100, 100, 300, 300))],
        IMAGE, threshold=0.35,
    )
    # Two 200x200 boxes overlapping in a 100x100 corner: 40000 + 40000 - 10000 px.
    assert found.features["plant_pot"].area_fraction == pytest.approx(0.07)


def test_unavailable_signals_are_reported_not_scored_as_absent():
    found = extract_features([], IMAGE, threshold=0.35)
    assert set(found.unavailable) == set(MISSING_FEATURES)
    assert "standing_water" in found.unavailable


def test_water_area_is_none_until_the_water_model_runs():
    assert extract_features([], IMAGE, threshold=0.35).as_dict()["water_area_fraction"] is None
    with_water = extract_features([], IMAGE, threshold=0.35, water_area_fraction=0.12)
    assert with_water.as_dict()["water_area_fraction"] == pytest.approx(0.12)
