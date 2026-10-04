"""Product scope for AquaPulse Vector Watch.

The system detects environmental signs, estimates risk, and proposes
verification and actions. It never diagnoses people, asserts pathogens,
or orders chemical spraying. Every AI- or rule-generated text shown to
users must pass `find_out_of_scope_claims` before being stored.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

PRODUCT_NAME = "AquaPulse Vector Watch"

GOAL = (
    "Phát hiện sớm các điều kiện môi trường có thể làm tăng nguy cơ "
    "liên quan đến muỗi, ruồi, ô nhiễm nước và phơi nhiễm."
)


class RiskCategory(StrEnum):
    MOSQUITO_BREEDING = "mosquito_breeding"
    FLY_AGGREGATION = "fly_aggregation"
    WATER_CONTAMINATION = "water_contamination"
    HUMAN_ANIMAL_EXPOSURE = "human_animal_exposure"
    POST_RAIN_HOTSPOT = "post_rain_hotspot"


RISK_CATEGORY_LABELS: dict[RiskCategory, str] = {
    RiskCategory.MOSQUITO_BREEDING: "Nguy cơ sinh sản của muỗi",
    RiskCategory.FLY_AGGREGATION: "Nguy cơ tập trung ruồi",
    RiskCategory.WATER_CONTAMINATION: "Nguy cơ ô nhiễm nước",
    RiskCategory.HUMAN_ANIMAL_EXPOSURE: "Nguy cơ tiếp xúc của người và vật nuôi",
    RiskCategory.POST_RAIN_HOTSPOT: "Nguy cơ hình thành điểm nóng sau mưa hoặc ngập",
}


class PipelineStage(StrEnum):
    DETECT_SIGNALS = "detect_signals"
    ESTIMATE_RISK = "estimate_risk"
    RECOMMEND_VERIFICATION = "recommend_verification"


PIPELINE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.DETECT_SIGNALS: "Phát hiện dấu hiệu",
    PipelineStage.ESTIMATE_RISK: "Ước tính rủi ro",
    PipelineStage.RECOMMEND_VERIFICATION: "Đề xuất xác minh và hành động",
}

NON_CLAIMS: tuple[str, ...] = (
    "Không chẩn đoán người bị bệnh.",
    "Không khẳng định một con muỗi có mang virus.",
    "Không kết luận nước có vi khuẩn chỉ bằng ảnh.",
    "Không thay thế xét nghiệm hoặc cơ quan y tế.",
    "Không tự động yêu cầu phun hóa chất.",
    # Section 20: notifications must not cause panic.
    "Không công bố ổ dịch khi chưa có xác nhận chính thức của cơ quan có thẩm quyền.",
)

DISCLAIMER = (
    "Kết quả là sàng lọc dấu hiệu môi trường, không phải chẩn đoán y tế "
    "hay kết quả xét nghiệm. Cần người có thẩm quyền xác minh trước khi hành động."
)


def _fold(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics so 'chẩn đoán' matches 'chan doan'."""
    text = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


# Each rule maps to the NON_CLAIMS entry it protects. Patterns run on folded text.
_OUT_OF_SCOPE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        NON_CLAIMS[0],
        re.compile(
            r"\bchan doan\b|\bdiagnos\w*|\b(bi|mac|nhiem) (benh )?(sot xuat huyet|dengue|"
            r"sot ret|zika|chikungunya|tieu chay|ta|thuong han)\b"
        ),
    ),
    (
        NON_CLAIMS[1],
        re.compile(
            r"\b(mang|nhiem|chua) (virus|vi rut|mam benh)\b|"
            r"\b(carr(y|ies|ying)|infected with) (the )?(virus|pathogen)"
        ),
    ),
    (
        NON_CLAIMS[2],
        re.compile(
            r"\b(nuoc )?(co|chua|nhiem) (vi khuan|e\.? ?coli|coliform|vibrio)\b|"
            r"\b(contains?|contaminated with) (bacteria|e\.? ?coli|coliform)"
        ),
    ),
    (
        NON_CLAIMS[4],
        re.compile(
            r"\b(phai|can|yeu cau|tien hanh) phun (hoa chat|thuoc|thuoc diet con trung)\b|"
            r"\b(must|should|required to) spray\b"
        ),
    ),
    (
        NON_CLAIMS[5],
        re.compile(
            r"\bo dich\b|\bdich [a-z ]{0,30}?(da |dang )?(xuat hien|bung phat|lan rong)\b|"
            r"\b(bung phat|lan rong) dich\b|\boutbreak\b"
        ),
    ),
)


def find_out_of_scope_claims(text: str) -> list[str]:
    """Return the non-claims violated by `text` (empty list if the text is in scope)."""
    folded = _fold(text)
    return [claim for claim, pattern in _OUT_OF_SCOPE_RULES if pattern.search(folded)]


def scope_summary() -> dict[str, object]:
    return {
        "product": PRODUCT_NAME,
        "goal": GOAL,
        "risk_categories": [
            {"id": category.value, "label": label}
            for category, label in RISK_CATEGORY_LABELS.items()
        ],
        "pipeline": [
            {"id": stage.value, "label": label} for stage, label in PIPELINE_LABELS.items()
        ],
        "non_claims": list(NON_CLAIMS),
        "disclaimer": DISCLAIMER,
    }
