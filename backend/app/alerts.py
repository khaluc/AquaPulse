"""Alerts: hotspots people act on (plan sections 17 and 20).

A hotspot is recomputed from the reports each time; an alert is the same place kept
over time, so it can be verified, resolved, and followed by notifications. After each
new report, `refresh` matches every current hotspot to an unresolved alert of the same
category within MATCH_RADIUS_M (update it) or opens a new one.

Level: the highest level among the alert's reports. The level of each report was
already held back by the risk engine when data was missing or the reporter disagreed
with the models, so an alert cannot reach orange on unconfirmed signs alone. Water
alerts (rivers, canals) follow the AquaPulse brief: yellow while nobody has checked on
site, orange once a volunteer or expert confirmed a report there, red only by an expert.

Each alert carries its evidence (EVIDENCE_* below): what happened, where the evidence
comes from, how confident it is, who should verify, and what people should do now.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app import notifications, repository, waterways
from app.auth import EXPERT, Reviewer
from app.errors import TaskError

CATEGORIES = ("vector", "sanitation", "water_quality")
CATEGORY_LABELS = {
    "vector": "nước đọng, điều kiện muỗi sinh sản",
    "sanitation": "ruồi, rác hữu cơ, vệ sinh",
    "water_quality": "nước bất thường",
}
LEVEL_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
MATCH_RADIUS_M = 300
ALERT_VERDICTS = ("verified", "resolved", "dismissed")


SIGNAL_WORDS = {
    **waterways.SIGNAL_LABELS,
    "standing_water": "nước đọng", "artificial_container": "vật chứa", "used_tire": "lốp xe",
    "organic_waste": "rác hữu cơ", "mosquito_larvae": "nghi có lăng quăng", "fly_cluster": "ruồi tập trung",
    "dead_animal": "xác động vật",
}
ADVICE = {
    "water_quality": "Tránh tiếp xúc trực tiếp với nước cho đến khi có kết quả kiểm tra.",
    "vector": "Đổ bỏ nước đọng, úp ngược hoặc đậy kín vật chứa quanh nhà.",
    "sanitation": "Không chạm tay trần vào rác hay xác động vật; báo tổ dân phố hoặc đơn vị vệ sinh môi trường.",
}
CLUSTER_RADIUS_M = 500
# Named first when counts tie: what matters most for people near the water.
SEVERITY = ["oil_sheen", "dead_fish", "dead_animal", "bad_odor", "foam", "unusual_color", "mosquito_larvae",
            "fly_cluster", "standing_water", "used_tire", "artificial_container", "organic_waste", "floating_trash"]


def _members(conn: psycopg.Connection, ids: list[UUID]) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT o.id, o.reporter_id, o.level, o.is_demo, o.confidence, o.answers, o.signals, o.expert_required,
               o.observed_at,
               EXTRACT(HOUR FROM o.observed_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::int AS local_hour,
               (SELECT count(*) FROM jsonb_each(coalesce(o.analysis -> 'vision' -> 'analysis' -> 'signals', '{}'))
                 WHERE value ->> 'detected' = 'true') AS vision_seen,
               EXISTS (SELECT 1 FROM verification_tasks t WHERE t.observation_id = o.id
                       AND (t.volunteer_verdict = 'confirmed' OR t.final_verdict = 'confirmed')) AS confirmed_on_site
        FROM observations o WHERE o.id = ANY(%s)
        """,
        (ids,),
    ).fetchall()


def _level(category: str, members: list[dict[str, Any]]) -> str:
    level = max((m["level"] for m in members), key=LEVEL_ORDER.__getitem__, default="green")
    if category != "water_quality":
        return level
    if any(m["confirmed_on_site"] for m in members):
        return "orange" if LEVEL_ORDER[level] <= LEVEL_ORDER["orange"] else level
    return "yellow"  # a cluster of unchecked reports is a suspicion, never more


def evidence(category: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """The five parts of an alert, as data (the page shows them; the message is built from them)."""
    signals = Counter()
    for m in members:
        seen = set(m["signals"] or []) | set(waterways._signals(m["answers"] or {}))
        signals.update(s for s in seen if s in SIGNAL_WORDS)
    times = [m["observed_at"] for m in members]
    hours = max(1, round((max(times) - min(times)).total_seconds() / 3600)) if times else 0
    confidence = (sum(waterways.effective_confidence(m) for m in members) / len(members)) if members else None
    night = sum(1 for m in members if m["local_hour"] not in waterways.DAYTIME)
    confirmed = sum(1 for m in members if m["confirmed_on_site"])
    return {
        "what": {"reports": len(members), "radius_m": CLUSTER_RADIUS_M, "hours": hours,
                 "signals": [{"signal": s, "label": SIGNAL_WORDS[s], "count": n}
                             for s, n in sorted(signals.items(), key=lambda kv: (-kv[1], SEVERITY.index(kv[0])))[:4]]},
        "evidence": {"reporters": len({m["reporter_id"] for m in members if m["reporter_id"]}),
                     "photos": len(members), "ai_suspected": sum(1 for m in members if m["vision_seen"]),
                     "confirmed_on_site": confirmed, "at_night": night},
        "confidence": None if confidence is None else round(confidence, 2),
        "confidence_label": waterways.confidence_label(confidence),
        "verifier": ("Cần chuyên gia môi trường lấy mẫu" if confirmed
                     else "Cần nhóm tình nguyện viên xác minh tại hiện trường")
                    if category == "water_quality" else
                    ("Cần chuyên gia xem" if any(m["expert_required"] for m in members)
                     else "Cần tình nguyện viên xác minh"),
        "advice": ADVICE.get(category, "Theo dõi và báo thêm nếu thấy thay đổi."),
    }


def refresh(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Bring alerts in line with the current hotspots. Returns what changed."""
    changes = []
    for category in CATEGORIES:
        for spot in repository.hotspots(conn, category=category, include_demo=True):
            members = _members(conn, spot["observation_ids"])
            level, is_demo = _level(category, members), all(m["is_demo"] for m in members)
            proof = evidence(category, members)
            existing = conn.execute(
                """
                SELECT id, level FROM alerts
                WHERE category = %(category)s AND status IN ('open', 'verified')
                  AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
                                 GREATEST(%(radius)s, %(spread)s))
                ORDER BY created_at LIMIT 1
                """,
                {"category": category, "lon": spot["longitude"], "lat": spot["latitude"],
                 "radius": MATCH_RADIUS_M, "spread": spot["spread_m"]},
            ).fetchone()
            values = {
                "category": category, "level": level, "lat": spot["latitude"], "lon": spot["longitude"],
                "spread": spot["spread_m"], "reports": spot["reports"], "reporters": spot["reporters"],
                "max_risk": spot["max_risk"], "hull": Jsonb(spot["hull"]), "ids": spot["observation_ids"],
                "demo": is_demo, "evidence": Jsonb(proof),
            }
            if existing is None:
                alert_id = conn.execute(
                    """
                    INSERT INTO alerts (category, level, latitude, longitude, spread_m, reports, reporters,
                                        max_risk, hull, observation_ids, is_demo, evidence)
                    VALUES (%(category)s, %(level)s, %(lat)s, %(lon)s, %(spread)s, %(reports)s, %(reporters)s,
                            %(max_risk)s, %(hull)s, %(ids)s, %(demo)s, %(evidence)s)
                    RETURNING id
                    """,
                    values,
                ).fetchone()["id"]
                notifications.alert_opened(conn, alert_id, category, level, spot, is_demo, proof)
                changes.append({"alert_id": alert_id, "change": "opened", "level": level})
                continue
            conn.execute(
                """
                UPDATE alerts SET level = %(level)s, latitude = %(lat)s, longitude = %(lon)s,
                    spread_m = %(spread)s, reports = %(reports)s, reporters = %(reporters)s,
                    max_risk = %(max_risk)s, hull = %(hull)s, observation_ids = %(ids)s,
                    is_demo = %(demo)s, evidence = %(evidence)s, updated_at = now()
                WHERE id = %(id)s
                """,
                {**values, "id": existing["id"]},
            )
            if LEVEL_ORDER[level] > LEVEL_ORDER[existing["level"]]:
                notifications.alert_escalated(conn, existing["id"], category, existing["level"], level, spot,
                                              is_demo, proof)
                changes.append({"alert_id": existing["id"], "change": "escalated", "level": level})
    return changes


def list_alerts(conn: psycopg.Connection, status: str | None, include_demo: bool) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, category, level, status, round(latitude::numeric, 4)::float AS latitude,
               round(longitude::numeric, 4)::float AS longitude, spread_m, reports, reporters, max_risk,
               hull, evidence, created_at, updated_at, verified_by, verified_at, resolved_at, note, is_demo
        FROM alerts
        WHERE (%(status)s::text IS NULL OR status = %(status)s)
          AND (is_demo = false OR %(demo)s)
        ORDER BY (status = 'open') DESC, max_risk DESC, updated_at DESC
        """,
        {"status": status, "demo": include_demo},
    ).fetchall()


def verify(conn: psycopg.Connection, alert_id: UUID, reviewer: Reviewer, verdict: str, note: str) -> dict[str, Any]:
    """An expert confirms, resolves or dismisses an alert (POST /alerts/{id}/verify)."""
    if reviewer.role != EXPERT:
        raise TaskError(403, "Chỉ chuyên gia mới xác minh được cảnh báo.")
    if verdict not in ALERT_VERDICTS:
        raise TaskError(422, f"Kết luận phải là một trong {ALERT_VERDICTS}.")
    row = conn.execute("SELECT * FROM alerts WHERE id = %s FOR UPDATE", (alert_id,)).fetchone()
    if row is None:
        raise TaskError(404, "Không có cảnh báo này.")
    if row["status"] in ("resolved", "dismissed"):
        raise TaskError(409, "Cảnh báo đã đóng.")
    conn.execute(
        """
        UPDATE alerts SET status = %(verdict)s, note = %(note)s, updated_at = now(),
            verified_by = %(who)s, verified_at = coalesce(verified_at, now()),
            resolved_at = CASE WHEN %(verdict)s IN ('resolved', 'dismissed') THEN now() END
        WHERE id = %(id)s
        """,
        {"verdict": verdict, "note": note, "who": reviewer.id, "id": alert_id},
    )
    if verdict == "resolved":
        notifications.alert_resolved(conn, alert_id, row)
    return {"id": alert_id, "status": verdict}
