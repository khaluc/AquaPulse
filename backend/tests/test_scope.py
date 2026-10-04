import pytest
from app.domain import NON_CLAIMS, RiskCategory, find_out_of_scope_claims
from app.main import app
from fastapi.testclient import TestClient


def test_scope_endpoint_lists_categories_pipeline_and_non_claims():
    body = TestClient(app).get("/scope").json()
    assert body["product"] == "AquaPulse Vector Watch"
    assert {c["id"] for c in body["risk_categories"]} == {c.value for c in RiskCategory}
    assert [s["id"] for s in body["pipeline"]] == [
        "detect_signals",
        "estimate_risk",
        "recommend_verification",
    ]
    assert body["non_claims"] == list(NON_CLAIMS)


@pytest.mark.parametrize(
    "text",
    [
        "Có nước đọng trong lốp xe, nguy cơ muỗi sinh sản cao. Đề nghị cán bộ y tế kiểm tra.",
        "Nước đục, nên lấy mẫu xét nghiệm để xác minh.",
        "Rác tích tụ gần khu dân cư, nguy cơ tập trung ruồi.",
    ],
)
def test_in_scope_text_passes(text):
    assert find_out_of_scope_claims(text) == []


@pytest.mark.parametrize(
    ("text", "claim_index"),
    [
        ("Chẩn đoán: người dân bị sốt xuất huyết", 0),
        ("chan doan benh nhan", 0),
        ("Muỗi trong ảnh mang virus dengue", 1),
        ("Nước này có vi khuẩn E. coli", 2),
        ("nuoc co vi khuan", 2),
        ("Yêu cầu phun hóa chất ngay", 4),
        ("The team must spray the area", 4),
    ],
)
def test_out_of_scope_text_is_flagged(text, claim_index):
    assert NON_CLAIMS[claim_index] in find_out_of_scope_claims(text)
