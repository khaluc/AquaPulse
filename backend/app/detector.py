"""Breeding-container detector: a YOLO model exported to ONNX, run with onnxruntime.

No PyTorch at serving time: it is heavy for a small server, and Smart App Control
blocks its unsigned DLLs on the team's Windows laptops. Pre- and post-processing
mirror Ultralytics' predict defaults (letterbox with gray padding, class-aware NMS
at IoU 0.7) so results match `yolo predict`.
"""

from __future__ import annotations

import ast
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "ml" / "runs" / "n_clean" / "weights" / "best.onnx"
FALLBACK_THRESHOLD = 0.35

PAD_VALUE = 114
NMS_IOU = 0.7
MAX_DETECTIONS = 300

# Display names and caveats per class. `validated` is False when the test split had
# too few real photos of the class to trust its numbers (see ml/runs/*/eval/report.json).
CLASS_INFO: dict[str, dict[str, object]] = {
    "used_tire": {
        "label": "Lốp xe cũ",
        "validated": False,
        "note": "Chưa kiểm chứng: tập test chỉ có 3 lốp xe chụp thật.",
    },
    "plastic_container": {"label": "Chai, vật chứa nhựa", "validated": True, "note": ""},
    "plant_pot": {"label": "Chậu cây", "validated": True, "note": ""},
    "coconut_shell": {"label": "Vỏ dừa", "validated": True, "note": ""},
    "drain_inlet": {"label": "Miệng cống", "validated": True, "note": ""},
}


class InvalidImageError(ValueError):
    pass


@dataclass(frozen=True)
class Detection:
    class_id: int
    name: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in original image pixels


@dataclass(frozen=True)
class Letterbox:
    scale: float
    pad_x: int
    pad_y: int


def load_image(data: bytes) -> Image.Image:
    """Decode an upload, honoring the EXIF rotation phones write instead of rotating pixels."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("File không phải ảnh hợp lệ (hỗ trợ JPG, PNG, WEBP).") from exc
    return ImageOps.exif_transpose(image).convert("RGB")


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, Letterbox]:
    """Resize keeping aspect ratio and pad to a square, as Ultralytics' LetterBox does."""
    width, height = image.size
    scale = min(size / width, size / height)
    new_w, new_h = round(width * scale), round(height * scale)
    pad_x = round((size - new_w) / 2 - 0.1)
    pad_y = round((size - new_h) / 2 - 0.1)
    pixels = np.asarray(image)
    if (new_w, new_h) != (width, height):
        # cv2 INTER_LINEAR, as Ultralytics uses. Pillow's bilinear antialiases when
        # shrinking, which shifted confidences by up to 0.3 on 1600x1200 phone photos.
        pixels = cv2.resize(pixels, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.uint8)
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = pixels
    tensor = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    return np.ascontiguousarray(tensor), Letterbox(scale, pad_x, pad_y)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    """Greedy non-maximum suppression; returns kept indices, highest score first."""
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i, rest = order[0], order[1:]
        keep.append(i)
        inter_w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        inter_h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = inter_w * inter_h
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def postprocess(
    output: np.ndarray,
    geometry: Letterbox,
    image_size: tuple[int, int],
    names: dict[int, str],
    conf_floor: float,
    iou_threshold: float = NMS_IOU,
) -> list[Detection]:
    """Turn raw YOLO output (1, 4 + classes, anchors) into detections in image pixels."""
    predictions = output[0].T
    scores = predictions[:, 4:]
    class_ids = scores.argmax(axis=1)
    confidences = scores[np.arange(len(scores)), class_ids]
    mask = confidences >= conf_floor
    if not mask.any():
        return []

    cx, cy, w, h = predictions[mask, :4].T
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    class_ids, confidences = class_ids[mask], confidences[mask]

    # Offset boxes by class so NMS never suppresses across classes.
    offset = class_ids[:, None].astype(np.float32) * (boxes.max() + 1)
    keep = nms(boxes + offset, confidences, iou_threshold)[:MAX_DETECTIONS]

    width, height = image_size
    boxes = boxes[keep]
    boxes[:, [0, 2]] = ((boxes[:, [0, 2]] - geometry.pad_x) / geometry.scale).clip(0, width)
    boxes[:, [1, 3]] = ((boxes[:, [1, 3]] - geometry.pad_y) / geometry.scale).clip(0, height)
    return [
        Detection(int(c), names[int(c)], float(s), tuple(round(float(v), 1) for v in box))
        for c, s, box in zip(class_ids[keep], confidences[keep], boxes, strict=True)
    ]


def threshold_from_report(model_path: Path) -> float:
    """Use the alert threshold chosen on the val split by ml/evaluate.py, if available."""
    report = model_path.parent.parent / "eval" / "report.json"
    try:
        return float(json.loads(report.read_text(encoding="utf-8"))["threshold"])
    except (OSError, KeyError, ValueError):
        return FALLBACK_THRESHOLD


class OnnxDetector:
    def __init__(self, model_path: Path):
        import onnxruntime as ort

        self.model_path = model_path
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        self.names: dict[int, str] = ast.literal_eval(meta["names"])
        self.imgsz: int = ast.literal_eval(meta["imgsz"])[0]
        self.input_name = self.session.get_inputs()[0].name
        self.threshold = threshold_from_report(model_path)
        self.description = meta.get("description", "")
        self.license = meta.get("license", "")

    def detect(self, image: Image.Image, conf_floor: float) -> tuple[list[Detection], float]:
        started = time.perf_counter()
        tensor, geometry = letterbox(image, self.imgsz)
        (output,) = self.session.run(None, {self.input_name: tensor})
        detections = postprocess(output, geometry, image.size, self.names, conf_floor)
        return detections, (time.perf_counter() - started) * 1000


def load_default_detector() -> OnnxDetector | None:
    path = Path(os.environ.get("AQUAPULSE_DETECTOR_MODEL", DEFAULT_MODEL_PATH))
    return OnnxDetector(path) if path.exists() else None
