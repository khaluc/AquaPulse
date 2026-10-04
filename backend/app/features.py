"""Turn detections into the feature dict the rule-based risk engine reads.

Two departures from the plan's pseudocode in section 9:

1. The plan keeps only `max(confidence)` per class. That throws away count, and
   count is the stronger signal: one plant pot and ten plant pots both score 0.9,
   but ten containers is a much bigger breeding surface. Both are kept here.

2. The plan's feature names (`standing_water`, `organic_waste`, `foam`,
   `oil_sheen`, `mosquito_larvae`) are not classes this model has. Only
   `used_tire` overlaps, and it is the one class the test split cannot validate.
   MISSING_FEATURES records them so the risk engine can state what it could not
   look for, instead of silently scoring as if the signal were absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from app.detector import CLASS_INFO, Detection

# Signals the plan's rules ask for that no trained class covers yet. Collecting the
# photos for these is tracked in the dataset notes (data/excluded.csv, README).
MISSING_FEATURES: tuple[str, ...] = (
    "standing_water",
    "organic_waste",
    "foam",
    "oil_sheen",
    "mosquito_larvae",
)


@dataclass(frozen=True)
class Feature:
    max_confidence: float
    count: int
    area_fraction: float  # share of the image covered by this class, after merging overlaps

    def as_dict(self) -> dict[str, float | int]:
        return {
            "max_confidence": round(self.max_confidence, 4),
            "count": self.count,
            "area_fraction": round(self.area_fraction, 4),
        }


@dataclass(frozen=True)
class FeatureSet:
    features: dict[str, Feature] = field(default_factory=dict)
    water_area_fraction: float | None = None  # None when the water model did not run
    water_confidence: float | None = None  # best in-container water patch; 0.0 if none found
    unavailable: tuple[str, ...] = MISSING_FEATURES
    # False when the container detector was not run at all (a river surface is not what it
    # was trained on). "Did not look" must not be read as "looked and saw nothing".
    detector_ran: bool = True

    def confidence(self, name: str) -> float:
        feature = self.features.get(name)
        return feature.max_confidence if feature else 0.0

    def count(self, name: str) -> int:
        feature = self.features.get(name)
        return feature.count if feature else 0

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> FeatureSet:
        """Inverse of as_dict, to re-score a stored report without re-running the models."""
        return cls(
            features={name: Feature(**values) for name, values in data["features"].items()},
            water_area_fraction=data.get("water_area_fraction"),
            water_confidence=data.get("water_confidence"),
            unavailable=tuple(data.get("unavailable", MISSING_FEATURES)),
            detector_ran=bool(data.get("detector_ran", True)),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "features": {name: f.as_dict() for name, f in sorted(self.features.items())},
            "water_area_fraction": (
                None if self.water_area_fraction is None else round(self.water_area_fraction, 4)
            ),
            "water_confidence": None if self.water_confidence is None else round(self.water_confidence, 4),
            "unavailable": list(self.unavailable),
            "detector_ran": self.detector_ran,
        }


def _merged_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Union area of axis-aligned boxes, so overlapping detections are not counted twice.

    Sweeps the distinct x edges and, in each vertical slab, merges the y intervals.
    """
    if not boxes:
        return 0.0
    xs = sorted({edge for box in boxes for edge in (box[0], box[2])})
    total = 0.0
    for left, right in pairwise(xs):
        width = right - left
        if width <= 0:
            continue
        spans = sorted((b[1], b[3]) for b in boxes if b[0] <= left and b[2] >= right)
        covered = 0.0
        current_top, current_bottom = None, None
        for top, bottom in spans:
            if current_bottom is None or top > current_bottom:
                if current_bottom is not None:
                    covered += current_bottom - current_top
                current_top, current_bottom = top, bottom
            else:
                current_bottom = max(current_bottom, bottom)
        if current_bottom is not None:
            covered += current_bottom - current_top
        total += width * covered
    return total


def extract_features(
    detections: list[Detection],
    image_size: tuple[int, int],
    threshold: float,
    water_area_fraction: float | None = None,
    water_confidence: float | None = None,
) -> FeatureSet:
    """Aggregate detections at or above `threshold` into per-class features."""
    width, height = image_size
    image_area = float(width * height) or 1.0
    grouped: dict[str, list[Detection]] = {}
    for detection in detections:
        if detection.confidence >= threshold:
            grouped.setdefault(detection.name, []).append(detection)

    features = {
        name: Feature(
            max_confidence=max(d.confidence for d in group),
            count=len(group),
            area_fraction=_merged_area([d.box for d in group]) / image_area,
        )
        for name, group in grouped.items()
    }
    # Classes the model knows but did not fire on are absent, not unavailable.
    unavailable = tuple(f for f in MISSING_FEATURES if f not in CLASS_INFO)
    return FeatureSet(
        features=features,
        water_area_fraction=water_area_fraction,
        water_confidence=water_confidence,
        unavailable=unavailable,
    )
