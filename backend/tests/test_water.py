import numpy as np
import pytest
from app.detector import Detection, Letterbox
from app.water import WaterInstance, attach_containers, postprocess, water_area_fraction

INPUT = 640
PROTO = 160


def _post(client, query=""):
    from tests.factories import jpeg_bytes, noise_photo

    return client.post(f"/detect{query}", files={"image": ("a.jpg", jpeg_bytes(noise_photo()), "image/jpeg")})


def _outputs(box_input_px, proto_region, score=0.9, n_protos=32):
    """Build a one-anchor segmentation output whose mask is a filled rectangle."""
    protos = np.full((1, n_protos, PROTO, PROTO), -10.0, dtype=np.float32)
    top, bottom, left, right = proto_region
    protos[0, 0, top:bottom, left:right] = 10.0

    output0 = np.zeros((1, 4 + 1 + n_protos, 1), dtype=np.float32)
    cx, cy, w, h = box_input_px
    output0[0, :4, 0] = [cx, cy, w, h]
    output0[0, 4, 0] = score
    output0[0, 5, 0] = 1.0  # first mask coefficient
    return output0, protos


def test_postprocess_returns_mask_polygon_in_original_pixels():
    output0, protos = _outputs((240, 240, 160, 160), (40, 80, 40, 80))
    geometry = Letterbox(scale=0.5, pad_x=0, pad_y=80)  # a 1280x960 photo letterboxed to 640
    found = postprocess(output0, protos, geometry, (1280, 960), INPUT, conf_floor=0.35)
    assert len(found) == 1
    water = found[0]
    assert water.confidence == pytest.approx(0.9)
    # 160x160 input px at scale 0.5 -> 320x320 original px
    assert water.area_px == pytest.approx(320 * 320, rel=0.02)
    xs = [x for x, _ in water.polygon]
    ys = [y for _, y in water.polygon]
    assert min(xs) == pytest.approx(320, abs=8)
    assert min(ys) == pytest.approx((160 - 80) / 0.5, abs=8)


def test_postprocess_drops_low_confidence():
    output0, protos = _outputs((240, 240, 160, 160), (40, 80, 40, 80), score=0.2)
    geometry = Letterbox(scale=1.0, pad_x=0, pad_y=0)
    assert postprocess(output0, protos, geometry, (640, 640), INPUT, conf_floor=0.35) == []


def _water(box, conf=0.8, area=100.0):
    return WaterInstance(conf, box, [(box[0], box[1]), (box[2], box[1]), (box[2], box[3])], area)


def test_water_outside_every_container_is_not_attached():
    inside = _water((110, 110, 190, 190))
    outside = _water((400, 400, 480, 480))
    detections = [Detection(2, "plant_pot", 0.9, (100, 100, 200, 200))]
    attach_containers([inside, outside], detections, detection_threshold=0.35)
    assert inside.container == "plant_pot"
    assert outside.container is None


def test_partly_overlapping_water_needs_most_of_its_box_inside():
    straddling = _water((150, 150, 350, 350))  # only a quarter sits in the container
    detections = [Detection(2, "plant_pot", 0.9, (100, 100, 250, 250))]
    attach_containers([straddling], detections, detection_threshold=0.35)
    assert straddling.container is None


def test_low_confidence_containers_do_not_hold_water():
    water = _water((110, 110, 190, 190))
    detections = [Detection(2, "plant_pot", 0.2, (100, 100, 200, 200))]
    attach_containers([water], detections, detection_threshold=0.35)
    assert water.container is None


def test_area_fraction_counts_only_water_in_containers():
    held = _water((110, 110, 190, 190), area=4000.0)
    held.container = "plant_pot"
    loose = _water((400, 400, 480, 480), area=9000.0)
    assert water_area_fraction([held, loose], (200, 200)) == pytest.approx(0.1)


def test_detect_endpoint_without_a_water_model(client):
    body = _post(client).json()
    assert body["water"]["available"] is False
    assert body["water"]["instances"] == []
    assert body["features"]["water_area_fraction"] is None


def test_detect_endpoint_marks_water_inside_a_container(client_with_water):
    body = _post(client_with_water).json()
    water = body["water"]
    assert water["available"] is True
    assert water["in_container"] == 1
    assert water["instances"][0]["container"] == "plastic_container"
    assert body["features"]["water_area_fraction"] > 0
    assert "89 ảnh" in water["note"]


def test_water_can_be_turned_off_per_request(client_with_water):
    body = _post(client_with_water, "?with_water=false").json()
    assert body["water"]["available"] is False
    assert body["features"]["water_area_fraction"] is None
