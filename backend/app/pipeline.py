"""Flow steps M-Q for one usable photo: detect, segment water, describe, fuse, score.

Shared by POST /detect (score only) and POST /observations (score, then store), so
the stored assessment is exactly what the reporter was shown.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from fastapi.concurrency import run_in_threadpool
from PIL import Image

from app.detector import CLASS_INFO
from app.domain import DISCLAIMER
from app.features import FeatureSet, extract_features
from app.fusion import VISION_VOTE, Fusion, ObservationGroup, ReportAnswers, YesNo, fuse
from app.quality import QualityReport
from app.review import CONFIRM, SHOW, ReviewRoute, route
from app.risk import RiskAssessment, assess
from app.vector_watch import VectorWatchResult, evaluate
from app.vision import VisionAnalysis, VisionError
from app.water import attach_containers, water_area_fraction

DETECTOR_SKIPPED = (
    "Ảnh này không chạy model nhận diện vật chứa: model chỉ được huấn luyện trên vật chứa có thể "
    "đọng nước. Mặt nước, rác nổi, váng dầu do model mô tả và người báo đánh giá."
)

WATER_NOTE = (
    "Model nước mới huấn luyện trên 89 ảnh (mask mAP50 0,51 trên tập test) và chỉ học "
    "nước trong vật chứa. Chỉ dùng làm bằng chứng hỗ trợ, không thay câu trả lời của người dân."
)

DETECTION_DISCLAIMER = (
    "Mô hình chỉ khoanh vùng vật có thể đọng nước. Nó không xác định có nước, "
    "lăng quăng hay muỗi trong ảnh. " + DISCLAIMER
)


@dataclass(frozen=True)
class PipelineResult:
    payload: dict[str, Any]
    fusion: Fusion
    assessment: RiskAssessment
    review: ReviewRoute
    vector_watch: VectorWatchResult


def score(
    features: FeatureSet,
    answers: ReportAnswers,
    vision: VisionAnalysis | None,
    quality_warnings: int,
    vision_expected: bool,
    nearby_reports: int | None = None,
) -> tuple[Fusion, RiskAssessment, ReviewRoute, VectorWatchResult]:
    """Flow steps O-U: merge sources, score the risk and the group, decide who looks next."""
    fusion = fuse(features, answers, vision, quality_warnings, vision_expected)
    assessment = assess(fusion, answers, vision)
    watch = evaluate(fusion, answers, features, nearby_reports)
    if watch.group is ObservationGroup.RIVER_HEALTH:
        assessment = hold_river_at_yellow(assessment)
    review = route(fusion, assessment, answers, watch)
    questions = reporter_questions(vision, answers)
    if questions:
        review = (ReviewRoute(CONFIRM, questions, ask_reporter=True, questions=questions)
                  if review.decision == SHOW else replace(review, ask_reporter=True, questions=questions))
    return fusion, assessment, review, watch


RIVER_UNVERIFIED_MAX = "yellow"


def hold_river_at_yellow(assessment: RiskAssessment) -> RiskAssessment:
    """River reports: before anyone has checked on site, the most a report says is "suspected".
    Orange needs a volunteer's confirmation on site, red an expert (see alerts.py)."""
    if assessment.level not in ("orange", "red"):
        return assessment
    return replace(
        assessment, level=RIVER_UNVERIFIED_MAX, level_label="Vàng",
        action="Nghi ngờ, chưa kết luận: cần xác minh tại hiện trường trước khi nâng mức cảnh báo.",
        verification_reasons=[*assessment.verification_reasons,
                               (f"Điểm {assessment.risk:.2f} đủ mức {assessment.level_label.lower()}, giữ ở vàng "
                                "vì chưa có người xác minh tại hiện trường.")],
    )


# What the photo may show, and how to ask the reporter about it in everyday words.
QUESTIONS = {
    "oil_sheen": ("váng dầu", "Bạn có thấy ánh cầu vồng hoặc mùi xăng dầu không?", "oil_sheen"),
    "foam": ("bọt trên mặt nước", "Bọt có đọng thành mảng, không tan không?", "foam"),
    "dead_animal": ("xác động vật hoặc cá chết", "Bạn có thấy xác động vật hay cá chết không?", "dead_fish"),
    "organic_waste": ("rác, lá mục", "Bạn có thấy rác hoặc lá mục trong nước không?", "organic_waste"),
}


def reporter_questions(vision: VisionAnalysis | None, answers: ReportAnswers) -> list[str]:
    """The vision model saw a sign the reporter did not mention: ask, with the model's certainty.
    The model's answer alone never raises a score (section 10); this only asks."""
    if vision is None:
        return []
    asked = []
    for signal, (label, question, field_name) in QUESTIONS.items():
        seen = vision.signals.get(signal)
        if not seen or not seen.detected or getattr(answers, field_name, YesNo.UNKNOWN) is not YesNo.UNKNOWN:
            continue
        percent = round(VISION_VOTE.get((True, seen.certainty), 0.5) * 100)
        asked.append(f"Ảnh cho thấy khả năng có {label}, độ tin cậy {percent}%. {question}")
    return asked


def rescore(payload: dict[str, Any], answers: ReportAnswers, nearby_reports: int | None = None) -> PipelineResult:
    """Re-score a stored report with corrected answers (section 16, steps H-I).

    Uses the stored model outputs instead of re-running the models on the stored photo,
    which was re-encoded and could give slightly different detections.
    """
    features = FeatureSet.from_dict(payload["features"])
    vision_block = payload.get("vision") or {}
    vision = VisionAnalysis.from_dict(vision_block["analysis"]) if vision_block.get("analysis") else None
    warnings = sum(1 for issue in payload["quality"]["issues"] if not issue["blocking"])
    expected = bool(vision_block.get("requested") and vision_block.get("available"))
    fusion, assessment, review, watch = score(features, answers, vision, warnings, expected, nearby_reports)
    updated = {
        **payload,
        "answers": answers.model_dump(mode="json"),
        "fusion": fusion.as_dict(),
        "assessment": assessment.as_dict(),
        "review": review.as_dict(),
        "vector_watch": watch.as_dict(),
    }
    return PipelineResult(updated, fusion, assessment, review, watch)


async def run_pipeline(
    state: Any,
    picture: Image.Image,
    answers: ReportAnswers,
    quality: QualityReport,
    *,
    conf_floor: float,
    with_water: bool,
    with_vision: bool,
    with_detector: bool = True,
    nearby_reports: int | None = None,
    lang: str = "vi",
) -> PipelineResult:
    """`with_detector`: run the container detector and the water model (photos of containers),
    or leave them out and let the vision model and the reporter describe the scene (a river
    surface, floating litter, an oil sheen: none of them are what the detector was trained on)."""
    detector = getattr(state, "detector", None)
    detections: list = []
    elapsed_ms = 0.0
    threshold = detector.threshold if detector is not None else 0.35
    detector_ran = detector is not None and with_detector
    if detector_ran:
        # Inference is CPU-bound; keep it off the event loop.
        detections, elapsed_ms = await run_in_threadpool(detector.detect, picture, conf_floor)

    segmenter = getattr(state, "water", None)
    water_ran = segmenter is not None and with_water and detector_ran
    water_instances, water_ms = [], None
    if water_ran:
        water_instances, water_ms = await run_in_threadpool(segmenter.segment, picture)
        # Water only counts inside a container the detector found: the water model was
        # trained on water in containers and otherwise paints foliage as water.
        attach_containers(water_instances, detections, threshold)

    vision_analysis, vision_error = None, None
    vision_client = getattr(state, "vision", None)
    if vision_client is not None and with_vision:
        try:
            vision_analysis = await run_in_threadpool(vision_client.analyze, picture, lang)
        except VisionError as exc:
            # The detector's answer still stands; the scene description is a bonus.
            vision_error = str(exc)

    held = [w.confidence for w in water_instances if w.container]
    features = replace(extract_features(
        detections, picture.size, threshold,
        water_area_fraction(water_instances, picture.size) if water_ran else None,
        (max(held) if held else 0.0) if water_ran else None,
    ), detector_ran=detector_ran)
    warnings = sum(1 for issue in quality.issues if not issue.blocking)
    fusion, assessment, review, watch = score(
        features, answers, vision_analysis, warnings,
        vision_expected=vision_client is not None and with_vision,
        nearby_reports=nearby_reports,
    )

    payload = {
        "image": {"width": picture.width, "height": picture.height},
        "quality": quality.as_dict(),
        "alert_threshold": threshold,
        "detector": {"available": detector is not None, "requested": with_detector, "ran": detector_ran,
                     "note": DETECTOR_SKIPPED if not detector_ran else ""},
        "inference_ms": round(elapsed_ms, 1),
        "detections": [
            {
                "class_id": d.class_id,
                "name": d.name,
                "label": CLASS_INFO.get(d.name, {}).get("label", d.name),
                "confidence": round(d.confidence, 4),
                "box": d.box,
                "above_threshold": d.confidence >= threshold,
            }
            for d in detections
        ],
        "water": {
            "available": water_ran,
            "inference_ms": None if water_ms is None else round(water_ms, 1),
            "instances": [w.as_dict() for w in water_instances],
            "in_container": sum(1 for w in water_instances if w.container),
            "note": WATER_NOTE,
        },
        "features": features.as_dict(),
        "answers": answers.model_dump(mode="json"),
        "fusion": fusion.as_dict(),
        "assessment": assessment.as_dict(),
        "review": review.as_dict(),
        "vector_watch": watch.as_dict(),
        "vision": {
            "available": vision_client is not None,
            "requested": with_vision,
            "error": vision_error,
            "analysis": None if vision_analysis is None else vision_analysis.as_dict(),
        },
        "flagged": any(d.confidence >= threshold for d in detections),
        "disclaimer": DETECTION_DISCLAIMER,
    }
    return PipelineResult(payload, fusion, assessment, review, watch)
