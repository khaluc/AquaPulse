import numpy as np
import pytest
from app import detector as det
from app.main import app
from fastapi.testclient import TestClient
from PIL import Image

from tests.factories import jpeg_bytes, noise_photo


def _jpeg() -> bytes:
    return jpeg_bytes(noise_photo(size=(800, 600)))


def test_letterbox_pads_to_square_and_keeps_aspect():
    tensor, geometry = det.letterbox(Image.new("RGB", (1280, 960), (255, 0, 0)), 640)
    assert tensor.shape == (1, 3, 640, 640)
    assert geometry.scale == pytest.approx(0.5)
    assert (geometry.pad_x, geometry.pad_y) == (0, 80)
    assert tensor[0, 0, 0, 320] == pytest.approx(114 / 255)  # top padding row
    assert tensor[0, 0, 320, 320] == pytest.approx(1.0)       # red channel of the photo


def test_nms_suppresses_overlaps_only():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    keep = det.nms(boxes, np.array([0.9, 0.8, 0.7]), 0.5)
    assert keep.tolist() == [0, 2]


def test_postprocess_maps_boxes_back_to_original_pixels():
    output = np.zeros((1, 6, 3), dtype=np.float32)  # 4 box values + 2 classes, 3 anchors
    output[0, :4, 0] = [320, 320, 100, 50]   # centred box in letterboxed space
    output[0, 5, 0] = 0.9                    # class 1
    output[0, :4, 1] = [322, 321, 100, 50]   # near-duplicate, same class -> suppressed
    output[0, 5, 1] = 0.6
    output[0, :4, 2] = [322, 321, 100, 50]   # same place, other class -> kept
    output[0, 4, 2] = 0.5
    geometry = det.Letterbox(scale=0.5, pad_x=0, pad_y=80)
    found = det.postprocess(output, geometry, (1280, 960), {0: "a", 1: "b"}, conf_floor=0.25)
    assert [(d.name, round(d.confidence, 2)) for d in found] == [("b", 0.9), ("a", 0.5)]
    assert found[0].box == pytest.approx((540.0, 430.0, 740.0, 530.0))


def test_load_image_rejects_non_images():
    with pytest.raises(det.InvalidImageError):
        det.load_image(b"not an image")


def test_detect_endpoint_flags_above_threshold(client):
    response = client.post("/detect", files={"image": ("a.jpg", _jpeg(), "image/jpeg")})
    body = response.json()
    assert response.status_code == 200
    assert body["image"] == {"width": 800, "height": 600}
    assert body["flagged"] is True
    assert [(d["label"], d["above_threshold"]) for d in body["detections"]] == [
        ("Chai, vật chứa nhựa", True),
        ("Lốp xe cũ", False),
    ]
    assert "không xác định có nước" in body["disclaimer"]


def test_detect_endpoint_rejects_bad_upload(client):
    response = client.post("/detect", files={"image": ("a.txt", b"hello", "text/plain")})
    assert response.status_code == 400


def test_detector_info_marks_unvalidated_classes(client):
    classes = {c["name"]: c for c in client.get("/detector").json()["classes"]}
    assert classes["used_tire"]["validated"] is False
    assert classes["plastic_container"]["validated"] is True


def test_detect_without_model_returns_503():
    app.state.detector = None
    app.state.water = None
    app.state.vision = None
    app.state.database = None
    try:
        with TestClient(app) as test_client:
            assert test_client.post("/detect", files={"image": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 503
    finally:
        del app.state.detector, app.state.water, app.state.vision, app.state.database


def test_demo_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AquaPulse" in response.text
