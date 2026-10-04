"""Stand-in detector so API tests do not need the ONNX model."""

from pathlib import Path

from app import detector as det
from app.water import WaterInstance


class FakeDetector:
    names = {0: "used_tire", 1: "plastic_container"}
    imgsz = 640
    threshold = 0.35
    license = "test"

    def __init__(self):
        self.model_path = Path("runs/fake/weights/best.onnx")

    def detect(self, image, conf_floor):
        found = [
            det.Detection(1, "plastic_container", 0.8, (10.0, 20.0, 110.0, 120.0)),
            det.Detection(0, "used_tire", 0.2, (5.0, 5.0, 50.0, 50.0)),
        ]
        return [d for d in found if d.confidence >= conf_floor], 12.5


class FakeSegmenter:
    """Returns one water patch inside the fake detector's plastic_container box."""

    imgsz = 640
    confidence = 0.35

    def __init__(self):
        self.model_path = Path("runs/fake_water/weights/best.onnx")

    def segment(self, image, conf_floor=None):
        patch = WaterInstance(0.7, (20.0, 30.0, 100.0, 110.0),
                              [(20.0, 30.0), (100.0, 30.0), (100.0, 110.0)], 6400.0)
        return [patch], 30.0
