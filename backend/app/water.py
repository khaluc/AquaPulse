"""Water surface segmentation, run with onnxruntime like the detector.

The model was trained on 89 photos of water *inside containers*, so it is weak:
mask mAP50 0.506 and recall 0.65 on a 19-image test split, and it happily paints
"water" on foliage. Two rules keep that weakness contained:

* Water is only counted when it sits inside a container the detector found
  (`attach_containers`). Foliage outside every container box is dropped.
* The risk engine treats the result as supporting evidence, never as proof. Whether
  water is present is primarily the reporter's answer ("Nước có đọng không?").

A YOLO segmentation model outputs 4 box values, the class scores, and 32 mask
coefficients per anchor, plus 32 prototype masks at a quarter of the input size.
A detection's mask is the sigmoid of its coefficients times the prototypes.
"""

from __future__ import annotations

import ast
import os
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.detector import Detection, Letterbox, letterbox, nms

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "ml" / "runs" / "water_seg_s" / "weights" / "best.onnx"
WATER_CONFIDENCE = 0.35
MASK_THRESHOLD = 0.5
NMS_IOU = 0.7
MAX_INSTANCES = 50
# Share of a water box that must fall inside a container box to count as "in" it.
CONTAINMENT_FRACTION = 0.6
CONTOUR_EPSILON = 1.5  # in prototype pixels, so ~6 input pixels


@dataclass
class WaterInstance:
    confidence: float
    box: tuple[float, float, float, float]
    polygon: list[tuple[float, float]]
    area_px: float
    container: str | None = None  # class name of the container it sits in, if any

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": round(self.confidence, 4),
            "box": [round(v, 1) for v in self.box],
            "polygon": [[round(x, 1), round(y, 1)] for x, y in self.polygon],
            "container": self.container,
        }


def _instance_mask(coefficients: np.ndarray, protos: np.ndarray) -> np.ndarray:
    flat = protos.reshape(protos.shape[0], -1)
    return 1.0 / (1.0 + np.exp(-(coefficients @ flat))).reshape(protos.shape[1:])


def _to_original(x: float, y: float, geometry: Letterbox, size: tuple[int, int]) -> tuple[float, float]:
    width, height = size
    return (
        min(max((x - geometry.pad_x) / geometry.scale, 0.0), width),
        min(max((y - geometry.pad_y) / geometry.scale, 0.0), height),
    )


def postprocess(
    output0: np.ndarray,
    output1: np.ndarray,
    geometry: Letterbox,
    image_size: tuple[int, int],
    input_size: int,
    conf_floor: float = WATER_CONFIDENCE,
) -> list[WaterInstance]:
    protos = output1[0]
    n_protos = protos.shape[0]
    predictions = output0[0].T
    n_classes = predictions.shape[1] - 4 - n_protos

    scores = predictions[:, 4 : 4 + n_classes].max(axis=1)
    keep_mask = scores >= conf_floor
    if not keep_mask.any():
        return []

    cx, cy, w, h = predictions[keep_mask, :4].T
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    scores = scores[keep_mask]
    coefficients = predictions[keep_mask, 4 + n_classes :]
    keep = nms(boxes, scores, NMS_IOU)[:MAX_INSTANCES]

    proto_scale = input_size / protos.shape[1]  # input pixels per prototype pixel
    instances: list[WaterInstance] = []
    for index in keep:
        mask = _instance_mask(coefficients[index], protos) >= MASK_THRESHOLD
        # Keep only the part inside the box, as Ultralytics does before upsampling.
        x1, y1, x2, y2 = boxes[index] / proto_scale
        cropped = np.zeros_like(mask)
        top, bottom = int(np.floor(y1)), int(np.ceil(y2))
        left, right = int(np.floor(x1)), int(np.ceil(x2))
        cropped[top:bottom, left:right] = mask[top:bottom, left:right]
        if not cropped.any():
            continue

        area_input_px = float(cropped.sum()) * proto_scale**2
        contours, _ = cv2.findContours(cropped.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        largest = max(contours, key=cv2.contourArea)
        simplified = cv2.approxPolyDP(largest, CONTOUR_EPSILON, True).reshape(-1, 2)
        polygon = [
            _to_original(float(px) * proto_scale, float(py) * proto_scale, geometry, image_size)
            for px, py in simplified
        ]
        box = (
            *_to_original(float(boxes[index][0]), float(boxes[index][1]), geometry, image_size),
            *_to_original(float(boxes[index][2]), float(boxes[index][3]), geometry, image_size),
        )
        instances.append(
            WaterInstance(float(scores[index]), box, polygon, area_input_px / geometry.scale**2)
        )
    return instances


def _overlap_fraction(inner: tuple[float, ...], outer: tuple[float, ...]) -> float:
    width = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    height = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return (width * height) / area if area > 0 else 0.0


def attach_containers(
    instances: list[WaterInstance],
    detections: list[Detection],
    detection_threshold: float,
    min_fraction: float = CONTAINMENT_FRACTION,
) -> list[WaterInstance]:
    """Mark each water patch with the container holding it; leaves `container=None` otherwise."""
    containers = [d for d in detections if d.confidence >= detection_threshold]
    for instance in instances:
        best, best_fraction = None, min_fraction
        for container in containers:
            fraction = _overlap_fraction(instance.box, container.box)
            if fraction >= best_fraction:
                best, best_fraction = container, fraction
        instance.container = best.name if best else None
    return instances


def water_area_fraction(instances: list[WaterInstance], image_size: tuple[int, int]) -> float:
    """Share of the image covered by water that sits inside a container."""
    width, height = image_size
    total = sum(i.area_px for i in instances if i.container)
    return total / float(width * height or 1)


class WaterSegmenter:
    def __init__(self, model_path: Path):
        import onnxruntime as ort

        self.model_path = model_path
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        self.names: dict[int, str] = ast.literal_eval(meta["names"])
        self.imgsz: int = ast.literal_eval(meta["imgsz"])[0]
        self.input_name = self.session.get_inputs()[0].name
        self.confidence = WATER_CONFIDENCE

    def segment(self, image: Image.Image, conf_floor: float | None = None) -> tuple[list[WaterInstance], float]:
        started = time.perf_counter()
        tensor, geometry = letterbox(image, self.imgsz)
        output0, output1 = self.session.run(None, {self.input_name: tensor})
        instances = postprocess(
            output0, output1, geometry, image.size, self.imgsz,
            self.confidence if conf_floor is None else conf_floor,
        )
        return instances, (time.perf_counter() - started) * 1000


def load_default_segmenter() -> WaterSegmenter | None:
    path = Path(os.environ.get("AQUAPULSE_WATER_MODEL", DEFAULT_MODEL_PATH))
    return WaterSegmenter(path) if path.exists() else None
