import pytest
from app import quality as q
from PIL import ImageEnhance

from tests.factories import jpeg_bytes, noise_photo, scene_photo

_photo = noise_photo


def codes(report):
    return {i.code for i in report.issues}


def test_sharp_photo_passes():
    report = q.check_image(_photo())
    assert report.usable
    assert report.issues == []
    assert report.metrics["width"] == 800
    assert len(report.metrics["phash"]) == 16


def test_blurry_photo_is_rejected():
    report = q.check_image(_photo(blur=6))
    assert not report.usable
    assert "too_blurry" in codes(report)


def test_dark_photo_is_rejected():
    report = q.check_image(_photo(brightness=0.1))
    assert not report.usable
    assert "too_dark" in codes(report)


def test_small_photo_is_rejected_and_medium_only_warns():
    assert not q.check_image(_photo(size=(240, 180))).usable
    warned = q.check_image(_photo(size=(400, 400)))
    assert warned.usable
    assert codes(warned) == {"small"}


def test_thresholds_match_the_measured_limits():
    """The measured limits: dark 30% (brightness 36) is borderline, dark 20% (24) is not usable."""
    assert pytest.approx(35.0) == q.DARK_REJECT
    assert pytest.approx(100.0) == q.BLUR_REJECT


def test_perceptual_hash_matches_near_duplicates_only():
    base = scene_photo(seed=1)
    same_scene = ImageEnhance.Brightness(base).enhance(1.15)
    other = scene_photo(seed=2)
    h_base = q.check_image(base).metrics["phash"]
    h_same = q.check_image(same_scene).metrics["phash"]
    h_other = q.check_image(other).metrics["phash"]
    assert q.hamming_distance(h_base, h_same) <= 6
    assert q.hamming_distance(h_base, h_other) > 12


def test_detect_endpoint_rejects_unusable_photo(client):
    blurry = jpeg_bytes(_photo(blur=6))
    response = client.post("/detect", files={"image": ("a.jpg", blurry, "image/jpeg")})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["quality"]["usable"] is False
    assert any(i["code"] == "too_blurry" and i["blocking"] for i in detail["quality"]["issues"])


def test_detect_endpoint_can_skip_the_quality_gate(client):
    blurry = jpeg_bytes(_photo(blur=6))
    response = client.post("/detect?skip_quality=true", files={"image": ("a.jpg", blurry, "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["quality"]["usable"] is False


def test_dark_photo_is_not_also_called_blurry():
    """Low light flattens contrast, so the blur score drops for a perfectly sharp photo."""
    report = q.check_image(_photo(brightness=0.1))
    assert codes(report) == {"too_dark"}
