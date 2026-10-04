"""Eco-Human Health Translator (AquaPulse brief): a concern in, a plain answer out.

Four questions from the brief. Each answer is built by rules from the segment passports,
never by a language model, and always carries the data it used, how certain it is, what
the system does not know, and advice that is not a medical recommendation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import psycopg

from app import waterways

QUESTIONS = {
    "children": "Có nên cho trẻ chơi gần đây không?",
    "odor": "Khu vực này có nguy cơ mùi hôi không?",
    "after_rain": "Sau trận mưa lớn, nơi nào cần kiểm tra trước?",
    "biodiversity": "Điểm nào đang ít dấu hiệu sự sống dưới nước nhất?",
}
NEEDS_SEGMENT = ("children", "odor")
ALWAYS_UNKNOWN = [
    "Chưa có kết quả xét nghiệm vi sinh, hóa chất hay độc tố: ảnh và câu trả lời không thay được xét nghiệm.",
]
DISCLAIMER = "Thông tin sàng lọc môi trường, không phải khuyến nghị y tế. Khi có triệu chứng, hãy hỏi cơ sở y tế."


class TranslatorError(ValueError):
    pass


def _data_used(p: dict[str, Any]) -> list[str]:
    part = p["participation"]
    used = [(f"{part['reports_30d']} quan sát của người dân trong 30 ngày "
             f"({part['reporters']} người, {part['confirmed_on_site']} đã xác nhận tại hiện trường)")]
    if p["rain"]["days"]:
        used.append("Lượng mưa đo được theo ngày (Open-Meteo)")
    if p["alerts"]:
        used.append(f"{len(p['alerts'])} cảnh báo đang mở")
    return used


def _certainty(p: dict[str, Any]) -> str:
    ix = p["indices"]
    if not ix["reports_7d"]:
        return "Thấp: không có quan sát nào trong 7 ngày qua."
    return f"{ix['confidence_label'].capitalize()} (độ tin cậy trung bình {ix['confidence']:.2f}, {ix['reports_7d']} quan sát trong 7 ngày)."


def _signal_count(p: dict[str, Any], *signals: str) -> int:
    return sum(a["count"] for a in p["anomalies"] if a["signal"] in signals)


def children(p: dict[str, Any]) -> dict[str, Any]:
    ix = p["indices"]
    hazards = _signal_count(p, "oil_sheen", "dead_fish", "bad_odor")
    if not ix["reports_7d"]:
        answer = (f"Chưa đủ dữ liệu cho {p['segment']['name']}: không có quan sát nào trong 7 ngày. "
                  "Không nên để trẻ lội hay chơi dưới nước kênh khi chưa biết tình trạng.")
    elif p["alerts"] or ix["anomalies_7d"]:
        answer = (f"Chưa nên. {p['segment']['name']} có {ix['anomalies_7d']} quan sát bất thường trong 7 ngày"
                  + (f" ({hazards} lần ghi nhận váng dầu, mùi lạ hoặc cá chết)" if hazards else "")
                  + (", và đang có cảnh báo chưa xác minh" if p["alerts"] else "")
                  + ". Có thể chơi trên bờ, xa mép nước; không lội, không chạm nước.")
    else:
        answer = (f"Chưa thấy dấu hiệu bất thường ở {p['segment']['name']} trong 7 ngày. Trẻ có thể chơi trên bờ; "
                  "vẫn không nên lội hay uống nước kênh, vì nước kênh đô thị chưa được kiểm tra.")
    return {"answer": answer, "advice": "Rửa tay bằng xà phòng sau khi chơi gần kênh; không để trẻ chạm vào rác nổi."}


def odor(p: dict[str, Any]) -> dict[str, Any]:
    ix = p["indices"]
    smells = _signal_count(p, "bad_odor")
    total = p["participation"]["reports_30d"]
    if not total:
        answer = f"Chưa có quan sát nào ở {p['segment']['name']} để trả lời."
    elif smells:
        answer = (f"Có. {smells} trong {total} quan sát 30 ngày qua ghi nhận mùi lạ. "
                  + ("Mùi thường nặng hơn sau mưa lớn, khi cống xả ra kênh." if p["rain"]["days"] else ""))
    else:
        answer = f"Chưa có quan sát nào trong {total} quan sát 30 ngày qua ghi nhận mùi lạ."
    trend = ix["trend"]["label"]
    return {"answer": answer + f" Xu hướng báo cáo bất thường: {trend.lower()}.",
            "advice": "Đóng cửa sổ hướng ra kênh lúc mùi nặng; báo thêm quan sát để hệ thống biết mùi kéo dài bao lâu."}


def after_rain(passports: list[dict[str, Any]], today: date) -> dict[str, Any]:
    ranked = []
    for p in passports:
        days = p["rain"]["days"] or []
        heavy = [d for d in days if d["mm"] >= waterways.HEAVY_RAIN_MM
                 and date.fromisoformat(d["day"]) > today - timedelta(days=7)]
        score = (2 * len(p["alerts"]) + p["indices"]["anomalies_7d"]
                 + (1 - (p["indices"]["confidence"] or 0)) + (1 if heavy else 0))
        reason = []
        if p["alerts"]:
            reason.append(f"{len(p['alerts'])} cảnh báo đang mở")
        if p["indices"]["anomalies_7d"]:
            reason.append(f"{p['indices']['anomalies_7d']} quan sát bất thường trong 7 ngày")
        if heavy:
            reason.append(f"mưa {max(d['mm'] for d in heavy):.0f} mm")
        if not p["indices"]["reports_7d"]:
            reason.append("chưa có ai quan sát tuần này")
        ranked.append((score, p["segment"]["name"], reason))
    ranked.sort(key=lambda r: r[0], reverse=True)
    lines = [f"{i}. {name}: {', '.join(reason) or 'ít dấu hiệu'}" for i, (_, name, reason) in enumerate(ranked[:3], 1)]
    return {"answer": "Nên kiểm tra theo thứ tự: " + "; ".join(lines) + ".",
            "advice": "Kiểm tra cửa xả cống và đoạn có báo cáo váng, mùi trước; chụp ảnh ban ngày để độ tin cậy cao hơn."}


def biodiversity(passports: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for p in passports:
        life = p["life"]
        if life["asked"]:
            rows.append((life["seen_alive"] / life["asked"], p["segment"]["name"], life, p["indices"]["eco"]))
    if not rows:
        return {"answer": "Chưa có ai trả lời câu hỏi về cá, tôm, côn trùng sống ở các đoạn kênh.",
                "advice": "Khi gửi quan sát, chọn mục tiêu 'Đa dạng sinh học' và trả lời có thấy sinh vật sống không."}
    rows.sort(key=lambda r: r[0])
    _, name, life, eco = rows[0]
    return {"answer": (f"{name}: chỉ {life['seen_alive']}/{life['asked']} quan sát thấy cá, tôm hay côn trùng sống"
                       + (f", điểm sinh thái {eco:.2f}" if eco is not None else "")
                       + ". Đây là số người dân nhìn thấy, không phải khảo sát loài."),
            "advice": "Cần khảo sát sinh học của chuyên gia để kết luận về đa dạng sinh học."}


def answer(conn: psycopg.Connection, question: str, segment_id: str | None, include_demo: bool) -> dict[str, Any]:
    if question not in QUESTIONS:
        raise TranslatorError(f"Câu hỏi phải là một trong {list(QUESTIONS)}.")
    today = conn.execute("SELECT (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS d").fetchone()["d"]
    if question in NEEDS_SEGMENT:
        if not segment_id:
            raise TranslatorError("Câu hỏi này cần chọn một đoạn kênh.")
        p = waterways.passport(conn, segment_id, include_demo)
        if p is None:
            raise TranslatorError("Không có đoạn kênh này.")
        body = children(p) if question == "children" else odor(p)
        used, certainty = _data_used(p), _certainty(p)
    else:
        ids = [r["id"] for r in conn.execute("SELECT id FROM waterway_segments ORDER BY seg_order").fetchall()]
        passports = [waterways.passport(conn, i, include_demo) for i in ids]
        body = after_rain(passports, today) if question == "after_rain" else biodiversity(passports)
        used = [f"Hộ chiếu rủi ro của {len(passports)} đoạn kênh"] + (
            ["Lượng mưa đo được theo ngày (Open-Meteo)"] if any(p["rain"]["days"] for p in passports) else [])
        seen = sum(p["indices"]["reports_7d"] for p in passports)
        certainty = f"Dựa trên {seen} quan sát trong 7 ngày trên toàn tuyến kênh."
    unknown = list(ALWAYS_UNKNOWN)
    if question == "biodiversity":
        unknown.append("Chưa định danh loài; 'có thấy sinh vật sống' là ghi nhận bằng mắt của người dân.")
    if question in ("children", "odor"):
        unknown.append("Chưa biết tình trạng ngoài các thời điểm có người quan sát.")
    return {"question": QUESTIONS[question], "answer": body["answer"], "data_used": used, "certainty": certainty,
            "unknown": unknown, "advice": body["advice"], "disclaimer": DISCLAIMER}
