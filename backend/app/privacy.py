"""Blur faces before a photo is stored or leaves the server (plan section 22).

Uses YuNet, OpenCV's own face detector (MIT licence, 230 KB ONNX file in
backend/models/). The models still see the original pixels in memory: only what is
written to disk, shown on the dashboard, or sent to an outside vision API is blurred.

Not covered: licence plates. OpenCV no longer ships a plate detector, and none of the
available ones are trained on Vietnamese plates; plates stay a known gap.
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "face_detection_yunet_2023mar.onnx"
SCORE_THRESHOLD = 0.6
MARGIN = 0.25          # blur a little beyond the detected box: hair, ears, chin
DETECT_MAX_SIDE = 1280  # detect on a reduced copy; boxes are scaled back


class FaceBlurrer:
    def __init__(self, model_path: Path = MODEL_PATH, detector=None):
        # cv2.FaceDetectorYN keeps state per call, so share one behind a lock.
        self._lock = threading.Lock()
        self._detector = detector or cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), SCORE_THRESHOLD)

    def faces(self, image: Image.Image) -> list[tuple[int, int, int, int]]:
        """Face boxes (x, y, w, h) in the image's own pixels."""
        rgb = np.asarray(image.convert("RGB"))
        height, width = rgb.shape[:2]
        scale = min(1.0, DETECT_MAX_SIDE / max(width, height))
        small = cv2.resize(rgb, (round(width * scale), round(height * scale))) if scale < 1 else rgb
        bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
        with self._lock:
            self._detector.setInputSize((bgr.shape[1], bgr.shape[0]))
            _, found = self._detector.detect(bgr)
        if found is None:
            return []
        return [tuple(int(v / scale) for v in row[:4]) for row in found]

    def blur(self, image: Image.Image) -> tuple[Image.Image, int]:
        boxes = self.faces(image)
        if not boxes:
            return image, 0
        pixels = np.asarray(image.convert("RGB")).copy()
        height, width = pixels.shape[:2]
        for x, y, w, h in boxes:
            dx, dy = int(w * MARGIN), int(h * MARGIN)
            left, top = max(0, x - dx), max(0, y - dy)
            right, bottom = min(width, x + w + dx), min(height, y + h + dy)
            if right <= left or bottom <= top:
                continue
            region = pixels[top:bottom, left:right]
            # Pixelate, then smooth: a blur alone can leave a face recognisable.
            small = cv2.resize(region, (max(1, (right - left) // 12), max(1, (bottom - top) // 12)))
            pixelated = cv2.resize(small, (right - left, bottom - top), interpolation=cv2.INTER_NEAREST)
            pixels[top:bottom, left:right] = cv2.GaussianBlur(pixelated, (0, 0), max(2, (right - left) / 20))
        return Image.fromarray(pixels), len(boxes)


@lru_cache(maxsize=1)
def default_blurrer() -> FaceBlurrer | None:
    """None when the model file is missing: photos are then stored unblurred, and /detector says so."""
    path = Path(os.environ.get("AQUAPULSE_FACE_MODEL", MODEL_PATH))
    return FaceBlurrer(path) if path.exists() else None


def blur_faces(image: Image.Image) -> tuple[Image.Image, int]:
    blurrer = default_blurrer()
    return blurrer.blur(image) if blurrer else (image, 0)
