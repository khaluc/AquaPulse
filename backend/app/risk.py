"""Rule-based risk score (flow steps Q-T) from section 12 of the plan.

Components, weights and value tables are the plan's. Four changes, each for a
failure measured on the plan's own formula:

1. Confidence C is reported next to the risk R, not multiplied into it. With
   R = C x (...), a water-filled tyre next to a school with children playing (R 0.555,
   orange) drops to green "theo dõi" when a new reporter makes C = 0.5. Low confidence
   should send a report to a person, not quietly downgrade it. `risk_times_confidence`
   keeps the plan's number visible for comparison.

2. A component nobody could observe is left out and the weights of the others are
   renormalised, instead of being scored as the lowest value. There is no weather data
   yet; scoring rain as "không mưa" would under-rate every report. Renormalising the
   other way round is just as wrong: with only V known, one pot of water scored R = V =
   0.8, red. So orange and red need data behind at least MIN_KNOWN_WEIGHT of the
   formula; with less, the level stops at yellow and the reporter is asked for more.

3. When the reporter and the models disagree (section 11), the level is capped at
   yellow and the reporter is asked to confirm: the alert does not rise on its own.

4. A sign only the vision model saw is flagged for a person but not scored (see
   `fusion.FusedSignal.unconfirmed`). On a real photo Qwen3-VL-2B claimed oil sheen on
   clean water, and that claim alone took the report to red.

Levels are prototype thresholds, not official public-health thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import find_out_of_scope_claims
from app.fusion import Contact, Fusion, NearbyPlace, RecentRain, ReportAnswers
from app.vision import VisionAnalysis

WEIGHTS = {"E": 0.25, "V": 0.30, "P": 0.15, "W": 0.15, "H": 0.15}

COMPONENT_NAMES = {
    "E": "Bất thường môi trường",
    "V": "Nguy cơ sinh sản vector",
    "P": "Gần khu dân cư",
    "W": "Thời tiết, mưa",
    "H": "Tiếp xúc người, vật nuôi",
}

# Environmental abnormality: the highest-valued sign present.
ENVIRONMENT_VALUES = {"oil_sheen": 0.9, "dead_animal": 0.9, "foam": 0.7, "organic_waste": 0.6}

# Vector breeding. The two starred rows are additions, flagged so the team can drop them:
# the water model finds water *inside containers*, which is the classic Aedes site even
# when the container is not a tyre; and a dry container fills at the next rain.
V_LARVAE = 1.0
V_WATER_TIRE = 0.9
V_WATER_ORGANIC = 0.8
V_WATER_OTHER_CONTAINER = 0.8  # * addition
V_WATER = 0.6
V_DRY_CONTAINER = 0.3          # * addition

PROXIMITY_VALUES = {NearbyPlace.FAR: 0.2, NearbyPlace.HOME: 0.6, NearbyPlace.SCHOOL: 0.9,
                    NearbyPlace.PLAYGROUND: 0.9}
WEATHER_VALUES = {RecentRain.NONE: 0.2, RecentRain.WITHIN_48H: 0.7, RecentRain.FLOOD_OR_HEAVY: 0.9}
CONTACT_VALUES = {Contact.NONE: 0.1, Contact.PASSING: 0.4, Contact.CHILDREN_NEARBY: 0.8,
                  Contact.DIRECT: 1.0}

LEVELS = (
    (0.75, "red", "Đỏ", "Chuyển cơ quan chuyên môn, sau khi đã có người xác minh"),
    (0.50, "orange", "Cam", "Xác minh và hành động cộng đồng"),
    (0.30, "yellow", "Vàng", "Cần thêm quan sát"),
    (0.00, "green", "Xanh", "Theo dõi"),
)
LOW_CONFIDENCE = 0.5
MIN_KNOWN_WEIGHT = 0.70

RECOMMENDATIONS = {
    "standing_water": "Đổ bỏ nước đọng, úp ngược hoặc đậy kín vật chứa.",
    "used_tire": "Thu gom lốp xe cũ, hoặc che để không đọng nước mưa.",
    "artificial_container": "Kiểm tra các vật chứa quanh đó sau mỗi trận mưa.",
    "organic_waste": "Thu gom rác hữu cơ, báo tổ dân phố nếu rác tồn đọng.",
    "mosquito_larvae": "Báo trạm y tế phường để cán bộ đến kiểm tra.",
    "oil_sheen": "Báo cơ quan môi trường địa phương để lấy mẫu kiểm tra.",
    "foam": "Báo cơ quan môi trường địa phương để kiểm tra nguồn nước.",
    "dead_animal": "Không chạm tay trần; báo đơn vị vệ sinh môi trường để xử lý.",
}


@dataclass(frozen=True)
class Component:
    value: float | None  # None: nobody could observe it, so it is left out of R
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"value": self.value, "reason": self.reason}


@dataclass(frozen=True)
class RiskAssessment:
    components: dict[str, Component]
    risk: float
    confidence: float
    level: str
    level_label: str
    action: str
    capped_by_conflict: bool
    capped_by_missing_data: bool
    known_weight: float
    needs_reporter_confirmation: bool
    needs_verification: bool
    verification_reasons: list[str] = field(default_factory=list)
    # The subset about the evidence itself (vision-only signs, an unvalidated class,
    # larvae, low confidence), without the reasons that come from the score's level.
    evidence_reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "risk": round(self.risk, 3),
            "confidence": round(self.confidence, 3),
            "risk_times_confidence": round(self.risk * self.confidence, 3),
            "level": self.level,
            "level_label": self.level_label,
            "action": self.action,
            "capped_by_conflict": self.capped_by_conflict,
            "capped_by_missing_data": self.capped_by_missing_data,
            "known_weight": round(self.known_weight, 2),
            "needs_reporter_confirmation": self.needs_reporter_confirmation,
            "needs_verification": self.needs_verification,
            "verification_reasons": self.verification_reasons,
            "components": {
                key: {"name": COMPONENT_NAMES[key], "weight": WEIGHTS[key], **c.as_dict()}
                for key, c in self.components.items()
            },
            "missing": self.missing,
            "recommendations": self.recommendations,
            "disclaimer": "Ngưỡng cho bản thử, không phải ngưỡng y tế chính thức.",
        }


def _environment(fusion: Fusion) -> Component:
    observed = [s for s in ENVIRONMENT_VALUES if fusion.signals[s].probability is not None]
    if not observed:
        return Component(None, "Chưa nguồn nào quan sát được rác, váng dầu, bọt hay xác động vật.")
    present = [s for s in observed if fusion.present(s)]
    if not present:
        return Component(0.0, "Không thấy dấu hiệu bất thường môi trường.")
    top = max(present, key=ENVIRONMENT_VALUES.get)
    return Component(ENVIRONMENT_VALUES[top], f"Có dấu hiệu: {', '.join(present)}.")


def _vector(fusion: Fusion) -> Component:
    water = fusion.present("standing_water")
    if fusion.present("mosquito_larvae"):
        return Component(V_LARVAE, "Có báo cáo ấu trùng, bắt buộc xác minh.")
    if water and fusion.present("used_tire"):
        return Component(V_WATER_TIRE, "Nước đọng trong lốp xe.")
    if water and fusion.present("organic_waste"):
        return Component(V_WATER_ORGANIC, "Nước đọng cạnh rác hữu cơ.")
    if water and fusion.present("artificial_container"):
        return Component(V_WATER_OTHER_CONTAINER, "Nước đọng trong vật chứa nhân tạo.")
    if water:
        return Component(V_WATER, "Có nước đọng.")
    if fusion.present("artificial_container"):
        return Component(V_DRY_CONTAINER, "Có vật chứa có thể đọng nước sau mưa.")
    return Component(0.0, "Không thấy nước đọng hay vật chứa.")


def _lookup(value, table, unknown_reason, label) -> Component:
    if value in table:
        return Component(table[value], label.get(value, value.value))
    return Component(None, unknown_reason)


def assess(
    fusion: Fusion,
    answers: ReportAnswers | None,
    vision: VisionAnalysis | None = None,
) -> RiskAssessment:
    answers = answers or ReportAnswers()
    components = {
        "E": _environment(fusion),
        "V": _vector(fusion),
        "P": _lookup(answers.nearby_place, PROXIMITY_VALUES, "Người báo chưa cho biết gần nơi nào.",
                     {NearbyPlace.FAR: "Xa khu dân cư", NearbyPlace.HOME: "Gần nhà ở",
                      NearbyPlace.SCHOOL: "Gần trường học", NearbyPlace.PLAYGROUND: "Gần khu vui chơi"}),
        "W": _lookup(answers.recent_rain, WEATHER_VALUES, "Chưa có dữ liệu mưa (chưa nối dịch vụ thời tiết).",
                     {RecentRain.NONE: "Không mưa gần đây", RecentRain.WITHIN_48H: "Mưa trong 48 giờ",
                      RecentRain.FLOOD_OR_HEAVY: "Ngập hoặc mưa lớn"}),
        "H": _lookup(answers.contact, CONTACT_VALUES, "Người báo chưa cho biết có ai tiếp xúc không.",
                     {Contact.NONE: "Không tiếp xúc", Contact.PASSING: "Người đi ngang",
                      Contact.CHILDREN_NEARBY: "Trẻ em chơi gần đó",
                      Contact.DIRECT: "Người hoặc vật nuôi tiếp xúc trực tiếp"}),
    }
    known = {k: c for k, c in components.items() if c.value is not None}
    total_weight = sum(WEIGHTS[k] for k in known)
    risk = sum(WEIGHTS[k] * c.value for k, c in known.items()) / total_weight if total_weight else 0.0
    missing = [COMPONENT_NAMES[k] for k in components if k not in known]

    level, label, action = next((lv, lb, ac) for floor, lv, lb, ac in LEVELS if risk >= floor)
    high = level in ("orange", "red")
    capped = capped_missing = False
    if fusion.reporter_conflicts and high:
        level, label, action = "yellow", "Vàng", "Cần người báo xác nhận trước khi nâng cảnh báo"
        capped = True
    elif total_weight < MIN_KNOWN_WEIGHT and high:
        level, label = "yellow", "Vàng"
        action = f"Cần thêm thông tin trước khi nâng cảnh báo: {', '.join(missing).lower()}"
        capped_missing = True

    level_reasons, reasons = [], []
    if risk >= 0.5 and capped_missing:
        level_reasons.append(f"Điểm tạm tính {risk:.2f} từ Cam trở lên nhưng chỉ dựa trên "
                             f"{total_weight:.0%} dữ liệu của công thức.")
    elif risk >= 0.5:  # also when a conflict capped the displayed level at yellow
        level_reasons.append("Mức rủi ro từ Cam trở lên.")
    if fusion.present("mosquito_larvae"):
        reasons.append("Có báo cáo ấu trùng.")
    if fusion.unconfirmed:
        reasons.append(
            f"Chỉ model mô tả bối cảnh thấy {', '.join(fusion.unconfirmed)}; chưa tính vào điểm."
        )
    elif vision is not None and vision.review_reasons:
        reasons.append(f"Model mô tả bối cảnh báo {', '.join(vision.review_reasons)}.")
    if fusion.confidence < LOW_CONFIDENCE and risk >= 0.3:
        reasons.append(f"Độ tin cậy thấp ({fusion.confidence:.2f}) nhưng rủi ro không thấp.")
    if components["V"].value == V_WATER_TIRE and set(fusion.signals["used_tire"].votes) == {"detector"}:
        reasons.append("Lốp xe chỉ do model phát hiện, mà lớp lốp xe chưa được kiểm chứng.")

    return RiskAssessment(
        components=components,
        risk=risk,
        confidence=fusion.confidence,
        level=level,
        level_label=label,
        action=action,
        capped_by_conflict=capped,
        capped_by_missing_data=capped_missing,
        known_weight=total_weight,
        needs_reporter_confirmation=bool(fusion.reporter_conflicts) or capped_missing,
        needs_verification=bool(level_reasons or reasons),
        verification_reasons=level_reasons + reasons,
        evidence_reasons=reasons,
        recommendations=_recommendations(fusion),
        missing=missing,
    )


def _recommendations(fusion: Fusion) -> list[str]:
    advice = [text for signal, text in RECOMMENDATIONS.items() if fusion.present(signal)]
    # Same promise as the vision model's text: nothing here may overstep section 1.
    return [text for text in advice if not find_out_of_scope_claims(text)]
