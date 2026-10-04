"""Who looks at a report next (plan section 16, flow steps U-Z).

The plan's chart routes on confidence first (> 0.85 show, 0.60-0.85 ask the reporter,
< 0.60 queue) and checks for serious signs only on the > 0.85 branch. A report with
oil sheen and C = 0.7 would then only be sent back to the reporter, although oil sheen
is on the plan's own must-verify list. Here the must-verify list is checked first and
applies whatever the confidence; the confidence bands decide only the rest.

    1. any must-verify case             -> verification queue
    2. reporter conflict, missing data,
       or C <= 0.85                      -> ask the reporter to confirm
    3. otherwise                         -> show the preliminary result

Some cases need an expert after the volunteer (section 16, step K): oil sheen,
chemical smell, a dead animal, and red alerts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.fusion import Fusion, ObservationGroup, Odor, ReportAnswers
from app.risk import RiskAssessment
from app.vector_watch import POSITIVE_AT, VectorWatchResult

SHOW_ABOVE = 0.85
VERIFY_BELOW = 0.60

SHOW, CONFIRM, VERIFY = "show", "confirm", "verify"
STATUS = {SHOW: "published", CONFIRM: "needs_confirmation", VERIFY: "needs_verification"}


@dataclass(frozen=True)
class ReviewRoute:
    decision: str
    reasons: list[str] = field(default_factory=list)
    expert_required: bool = False
    expert_reasons: list[str] = field(default_factory=list)
    ask_reporter: bool = False  # also ask the reporter, even when a person will verify
    # Specific questions for the reporter, e.g. "the photo may show oil sheen (70%): do you see ...?"
    questions: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return STATUS[self.decision]

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "status": self.status,
            "reasons": self.reasons,
            "expert_required": self.expert_required,
            "expert_reasons": self.expert_reasons,
            "ask_reporter": self.ask_reporter,
            "questions": self.questions,
        }


def _seen(fusion: Fusion, signal: str) -> bool:
    """Present, or claimed only by the vision model: either way a person should look."""
    fused = fusion.signals.get(signal)
    return bool(fused and (fused.present or fused.unconfirmed))


def route(
    fusion: Fusion,
    assessment: RiskAssessment,
    answers: ReportAnswers | None,
    watch: VectorWatchResult | None = None,
) -> ReviewRoute:
    answers = answers or ReportAnswers()
    verify: list[str] = []
    expert: list[str] = []

    # Vector Watch: some groups always go to a person, whatever their score.
    if watch is not None:
        spec = watch.spec
        if spec.always_verify:
            verify.append(f"Nhóm '{spec.label}': {spec.verification.lower()}.")
            if spec.expert:
                expert.append(f"Nhóm '{spec.label}' cần chuyên gia.")
        if (watch.group is ObservationGroup.WATER_QUALITY_SIGNAL
                and (watch.environmental_signal or 0) >= POSITIVE_AT):
            verify.append(f"Tín hiệu nước bất thường {watch.environmental_signal:.2f}: đề xuất lấy mẫu.")
            expert.append("Tín hiệu nước bất thường cần chuyên gia hoặc phòng thí nghiệm lấy mẫu.")

    if _seen(fusion, "mosquito_larvae"):
        verify.append("Nghi ngờ lăng quăng.")
    if _seen(fusion, "oil_sheen"):
        verify.append("Váng dầu.")
        expert.append("Váng dầu cần cơ quan môi trường lấy mẫu.")
    if _seen(fusion, "dead_animal"):
        verify.append("Xác động vật.")
        expert.append("Xác động vật cần đơn vị vệ sinh môi trường xử lý.")
    if answers.odor is Odor.CHEMICAL:
        verify.append("Nước có mùi hóa chất.")
        expert.append("Mùi hóa chất cần chuyên gia môi trường.")
    # The level after section 11/12 caps: a report held at yellow for missing data or a
    # reporter conflict goes back to the reporter first, not to a volunteer.
    if assessment.level in ("orange", "red"):
        verify.append(f"Cảnh báo mức {assessment.level_label.lower()} (R = {assessment.risk:.2f}).")
    if assessment.level == "red":
        expert.append("Mức đỏ chỉ chuyển cơ quan chuyên môn sau khi chuyên gia xem.")
    if fusion.confidence < VERIFY_BELOW:
        verify.append(f"Độ tin cậy thấp (C = {fusion.confidence:.2f} < {VERIFY_BELOW}).")
    verify.extend(c.message for c in fusion.model_conflicts)
    # What the risk engine flagged about the evidence (vision-only signs, an unvalidated class, ...).
    verify.extend(assessment.evidence_reasons)

    ask_reporter = assessment.needs_reporter_confirmation
    if verify:
        return ReviewRoute(VERIFY, list(dict.fromkeys(verify)), bool(expert), expert, ask_reporter)

    confirm = [c.message for c in fusion.reporter_conflicts]
    if assessment.capped_by_missing_data:
        confirm.append(assessment.action)
    if fusion.confidence <= SHOW_ABOVE:
        confirm.append(f"Độ tin cậy trung bình (C = {fusion.confidence:.2f}); nhờ người báo xác nhận.")
    if confirm:
        return ReviewRoute(CONFIRM, confirm, ask_reporter=True)
    return ReviewRoute(SHOW, ["Độ tin cậy cao, không có dấu hiệu bắt buộc xác minh."])
