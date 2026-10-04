"""Notifications (plan section 20): calm, factual, never an outbreak claim.

Stored as an outbox: area notices carry a location and are read by anyone watching a
radius around a point; personal notices carry a user id. Delivery (web push, Zalo, SMS)
is not built yet; clients poll GET /notifications.

Every message goes through `find_out_of_scope_claims`, which since section 20 also
rejects "ổ dịch" / "dịch … bùng phát" wording. A message that fails is not stored.
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.domain import find_out_of_scope_claims

LEVEL_LABELS = {"green": "xanh", "yellow": "vàng", "orange": "cam", "red": "đỏ"}
CATEGORY_WORDS = {
    "vector": "nước đọng",
    "sanitation": "ruồi, rác hữu cơ",
    "water_quality": "nước bất thường",
}
NOT_CONCLUDED = {
    "vector": "Hệ thống chưa kết luận có muỗi truyền bệnh.",
    "sanitation": "Hệ thống chưa kết luận về tác nhân gây bệnh.",
    "water_quality": "Hệ thống chưa kết luận nước bị nhiễm khuẩn hay độc tố.",
}


class UnsafeMessage(ValueError):
    pass


def _store(conn: psycopg.Connection, kind: str, message: str, *, level: str | None = None,
           user_id: str | None = None, latitude: float | None = None, longitude: float | None = None,
           ref_id: str | None = None, is_demo: bool = False) -> None:
    claims = find_out_of_scope_claims(message)
    if claims:
        raise UnsafeMessage(f"Thông báo vượt phạm vi: {claims}")
    conn.execute(
        """
        INSERT INTO notifications (kind, level, user_id, latitude, longitude, message, ref_id, is_demo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (kind, level, user_id, latitude, longitude, message, ref_id, is_demo),
    )


def evidence_message(category: str, level_text: str, proof: dict[str, Any] | None, reports: int) -> str:
    """The brief's structure: what happened, the evidence, confidence, who verifies, what to do now."""
    if not proof:
        return (f"{level_text}: khu vực này có {reports} báo cáo về {CATEGORY_WORDS[category]} trong 72 giờ qua. "
                f"{NOT_CONCLUDED[category]} Bạn có thể tham gia xác minh điểm này.")
    what, ev = proof["what"], proof["evidence"]
    signs = " và ".join(s["label"] for s in what["signals"][:2]) or CATEGORY_WORDS[category]
    source = f"{ev['reporters']} người khác nhau gửi ảnh"
    if ev["confirmed_on_site"]:
        source += f", {ev['confirmed_on_site']} báo cáo đã được xác nhận tại hiện trường"
    elif ev["ai_suspected"]:
        source += f"; AI chỉ gán nghi ngờ ở {ev['ai_suspected']} ảnh, chưa kết luận"
    confidence = "" if proof["confidence"] is None else f" ({proof['confidence']:.2f})".replace(".", ",")
    if ev.get("at_night", 0) * 2 > what["reports"]:
        confidence += ", phần lớn ảnh chụp ban đêm"
    return (f"{level_text}: {what['reports']} quan sát trong bán kính {what['radius_m']} m ghi nhận {signs} "
            f"trong {what['hours']} giờ. Bằng chứng: {source}. Độ tin cậy {proof['confidence_label']}{confidence}. "
            f"{NOT_CONCLUDED[category]} {proof['verifier']}. {proof['advice']}")


def alert_opened(conn, alert_id, category: str, level: str, spot: dict[str, Any], is_demo: bool,
                 proof: dict[str, Any] | None = None) -> None:
    _store(conn, "alert_opened",
           evidence_message(category, f"Cảnh báo mức {LEVEL_LABELS[level]}", proof, spot["reports"]),
           level=level, latitude=spot["latitude"], longitude=spot["longitude"], ref_id=str(alert_id),
           is_demo=is_demo)


def alert_escalated(conn, alert_id, category: str, old: str, new: str, spot: dict[str, Any], is_demo: bool,
                    proof: dict[str, Any] | None = None) -> None:
    _store(conn, "alert_escalated",
           evidence_message(category, f"Cảnh báo tăng từ mức {LEVEL_LABELS[old]} lên {LEVEL_LABELS[new]}", proof,
                            spot["reports"]),
           level=new, latitude=spot["latitude"], longitude=spot["longitude"], ref_id=str(alert_id),
           is_demo=is_demo)


def alert_resolved(conn, alert_id, alert: dict[str, Any]) -> None:
    _store(conn, "alert_resolved",
           f"Điểm {CATEGORY_WORDS.get(alert['category'], 'cảnh báo')} gần bạn đã được xử lý và xác nhận.",
           level="green", latitude=alert["latitude"], longitude=alert["longitude"], ref_id=str(alert_id),
           is_demo=alert["is_demo"])


def task_nearby(conn, task_id, latitude: float, longitude: float, reasons: list[str], is_demo: bool) -> None:
    # The reasons stay in the task for reviewers; the public notice is fixed text.
    _store(conn, "task_nearby",
           "Có một điểm cần xác minh gần bạn. Bạn có thể nhận nhiệm vụ kiểm tra tại chỗ.",
           latitude=latitude, longitude=longitude, ref_id=str(task_id), is_demo=is_demo)


def verification_result(conn, reporter_id: str | None, observation_id, verdict: str, is_demo: bool) -> None:
    if not reporter_id:
        return
    text = ("Báo cáo của bạn đã được xác minh. Cảm ơn bạn!" if verdict == "confirmed"
            else "Báo cáo của bạn đã được kiểm tra; người xác minh không thấy dấu hiệu như mô tả.")
    _store(conn, "verification_result", text, user_id=reporter_id, ref_id=str(observation_id), is_demo=is_demo)


def for_area(conn, latitude: float, longitude: float, radius_m: float, hours: int,
             include_demo: bool) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, kind, level, message, ref_id, created_at,
               round(ST_Distance(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography))::int
                   AS distance_m
        FROM notifications
        WHERE user_id IS NULL AND geom IS NOT NULL
          AND created_at >= now() - make_interval(hours => %(hours)s)
          AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius)s)
          AND (is_demo = false OR %(demo)s)
        ORDER BY created_at DESC
        LIMIT 100
        """,
        {"lat": latitude, "lon": longitude, "radius": radius_m, "hours": hours, "demo": include_demo},
    ).fetchall()


def for_user(conn, user_id: str, hours: int) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, kind, level, message, ref_id, created_at
        FROM notifications
        WHERE user_id = %s AND created_at >= now() - make_interval(hours => %s)
        ORDER BY created_at DESC LIMIT 100
        """,
        (user_id, hours),
    ).fetchall()
