"""Image quality gate: step K/L of the flow, run before the detector.

Thresholds are not guesses. They come from running the detector on the 167 test
photos after degrading them, and finding where recall collapses (baseline box
recall 0.826, image-level recall 0.952):

    degradation   brightness  blur score  box recall
    none                 122        1533       0.826
    blur 1px             122         167       0.731   <- still usable
    blur 1.5px           122          48       0.573   <- unusable
    dark 50%              61         385       0.785   <- still usable
    dark 30%              36         140       0.684   <- borderline
    dark 20%              24          63       0.509   <- unusable
    resized to 320px     122         557       0.718   <- borderline
    resized to 224px     122         415       0.617   <- unusable

`blur score` is the variance of the Laplacian measured after resizing to 512x512.
Measuring it at native size makes the number depend on the phone's resolution, so
the same threshold would behave differently on a 12 MP and a 2 MP photo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

BLUR_NORMALIZED_SIZE = 512

MIN_SIDE_REJECT = 320
MIN_SIDE_WARN = 480
BLUR_REJECT = 100.0
BLUR_WARN = 250.0
DARK_REJECT = 35.0
DARK_WARN = 60.0
BRIGHT_REJECT = 235.0  # washed out, e.g. shooting into the sun
PHASH_SIZE = 8


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    value: float
    threshold: float
    blocking: bool


@dataclass(frozen=True)
class QualityReport:
    usable: bool
    metrics: dict[str, float | int | str]
    issues: list[Issue] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "usable": self.usable,
            "metrics": self.metrics,
            "issues": [
                {"code": i.code, "message": i.message, "value": round(i.value, 1),
                 "threshold": i.threshold, "blocking": i.blocking}
                for i in self.issues
            ],
        }


def blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian at a fixed size, so the value does not track megapixels."""
    resized = cv2.resize(gray, (BLUR_NORMALIZED_SIZE, BLUR_NORMALIZED_SIZE), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(resized, cv2.CV_64F).var())


def perceptual_hash(gray: np.ndarray, size: int = PHASH_SIZE) -> str:
    """Difference hash; two photos of the same scene give a small Hamming distance.

    Returned for the caller to store: deciding that a submission duplicates an earlier
    one needs the other submissions, which live in the database, not in this module.
    """
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    return f"{int(''.join('1' if b else '0' for b in bits.flatten()), 2):0{size * size // 4}x}"


def hamming_distance(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def check_image(image: Image.Image) -> QualityReport:
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    brightness = float(gray.mean())
    sharpness = blur_score(gray)
    shortest = min(width, height)

    issues: list[Issue] = []

    def add(code: str, message: str, value: float, threshold: float, blocking: bool) -> None:
        issues.append(Issue(code, message, value, threshold, blocking))

    if shortest < MIN_SIDE_REJECT:
        add("too_small", f"Ảnh quá nhỏ ({width}x{height}). Cần cạnh ngắn ít nhất {MIN_SIDE_REJECT} px.",
            shortest, MIN_SIDE_REJECT, True)
    elif shortest < MIN_SIDE_WARN:
        add("small", f"Ảnh hơi nhỏ ({width}x{height}), kết quả có thể kém chính xác.",
            shortest, MIN_SIDE_WARN, False)

    too_dark = brightness < DARK_REJECT
    # Darkness flattens contrast, which drags the blur score down too. Reporting both
    # would send the reporter chasing camera shake when the real problem is the light.
    if not too_dark:
        if sharpness < BLUR_REJECT:
            add("too_blurry", "Ảnh quá mờ. Giữ máy yên và chụp lại.", sharpness, BLUR_REJECT, True)
        elif sharpness < BLUR_WARN:
            add("blurry", "Ảnh hơi mờ, nên chụp lại cho nét hơn.", sharpness, BLUR_WARN, False)

    if too_dark:
        add("too_dark", "Ảnh quá tối. Chụp lại khi đủ sáng hoặc bật đèn.", brightness, DARK_REJECT, True)
    elif brightness < DARK_WARN:
        add("dark", "Ảnh hơi tối, kết quả có thể kém chính xác.", brightness, DARK_WARN, False)
    elif brightness > BRIGHT_REJECT:
        add("too_bright", "Ảnh bị cháy sáng. Tránh chụp ngược nắng.", brightness, BRIGHT_REJECT, True)

    return QualityReport(
        usable=not any(i.blocking for i in issues),
        metrics={
            "width": width,
            "height": height,
            "brightness": round(brightness, 1),
            "blur_score": round(sharpness, 1),
            "phash": perceptual_hash(gray),
        },
        issues=issues,
    )
