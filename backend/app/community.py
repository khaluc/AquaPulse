"""Points, badges and community tasks (plan section 19).

Quality and verified action are rewarded, volume is not:

    +10  a report with photo and GPS that passed the quality gate and is not a duplicate
         (at most DAILY_REPORT_AWARDS a day, so sending many photos does not pay)
    +20  a report of yours was verified as real
    +30  a clean-up task completed (or the task's own reward)
    +15  an after-photo from a clean-up
    +5   checking someone else's report on site

Every award is keyed on (user, reason, reference), so the same action never pays twice.
Reporter ids are pseudonymous and there is no login for citizens yet, so points can be
gamed by someone who reuses another reporter's id: fine for a pilot, not for prizes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from app.auth import EXPERT, Reviewer
from app.errors import TaskError

POINTS = {"report": 10, "report_verified": 20, "task_completed": 30, "after_photo": 15, "peer_check": 5}
DAILY_REPORT_AWARDS = 5

BADGES = {
    "water_watcher": ("Water Watcher", "3 báo cáo nước đọng, vật chứa được xác minh"),
    "vector_scout": ("Vector Scout", "3 báo cáo về muỗi hoặc điều kiện muỗi được xác minh"),
    "community_verifier": ("Community Verifier", "5 lần kiểm tra báo cáo của người khác"),
    "river_guardian": ("River Guardian", "2 báo cáo nước bất thường được xác minh"),
    "post_rain_responder": ("Post-Rain Responder", "3 báo cáo sau mưa hoặc ngập"),
}


def award(conn: psycopg.Connection, user_id: str | None, reason: str, ref_id: Any,
          points: int | None = None) -> int:
    """Give points once per (user, reason, reference); returns what was given (0 if not)."""
    if not user_id:
        return 0
    amount = POINTS[reason] if points is None else points
    row = conn.execute(
        """
        INSERT INTO points_ledger (user_id, points, reason, ref_id) VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, reason, ref_id) DO NOTHING RETURNING points
        """,
        (user_id, amount, reason, str(ref_id)),
    ).fetchone()
    return row["points"] if row else 0


def award_report(conn: psycopg.Connection, reporter_id: str | None, observation_id: UUID,
                 duplicate: bool) -> int:
    if not reporter_id or duplicate:
        return 0
    today = conn.execute(
        """
        SELECT count(*) AS n FROM points_ledger
        WHERE user_id = %s AND reason = 'report'
          AND created_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Ho_Chi_Minh') AT TIME ZONE 'Asia/Ho_Chi_Minh'
        """,
        (reporter_id,),
    ).fetchone()["n"]
    if today >= DAILY_REPORT_AWARDS:
        return 0
    return award(conn, reporter_id, "report", observation_id)


def profile(conn: psycopg.Connection, user_id: str) -> dict[str, Any]:
    total = conn.execute("SELECT coalesce(sum(points), 0) AS p FROM points_ledger WHERE user_id = %s",
                         (user_id,)).fetchone()["p"]
    counts = conn.execute(
        """
        SELECT
          count(*) FILTER (WHERE status = 'verified' AND vector_group = 'aedes_breeding_risk') AS aedes,
          count(*) FILTER (WHERE status = 'verified' AND risk_domain = 'vector') AS vector,
          count(*) FILTER (WHERE status = 'verified' AND vector_group = 'water_quality_signal') AS water,
          count(*) FILTER (WHERE status <> 'dismissed' AND duplicate_of IS NULL
                           AND answers ->> 'recent_rain' IN ('within_48h', 'flood_or_heavy')) AS after_rain
        FROM observations WHERE reporter_id = %s
        """,
        (user_id,),
    ).fetchone()
    checks = conn.execute(
        "SELECT count(*) AS n FROM verification_events WHERE actor_id = %s AND action LIKE 'submitted:%%'",
        (user_id,),
    ).fetchone()["n"]
    earned = {
        "water_watcher": counts["aedes"] >= 3,
        "vector_scout": counts["vector"] >= 3,
        "community_verifier": checks >= 5,
        "river_guardian": counts["water"] >= 2,
        "post_rain_responder": counts["after_rain"] >= 3,
    }
    history = conn.execute(
        "SELECT points, reason, ref_id, created_at FROM points_ledger WHERE user_id = %s "
        "ORDER BY created_at DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    return {
        "user_id": user_id,
        "points": total,
        "badges": [{"id": key, "name": BADGES[key][0], "rule": BADGES[key][1], "earned": got}
                   for key, got in earned.items()],
        "history": history,
    }


def mask(user_id: str) -> str:
    """Public boards show no names or full ids (section 22)."""
    return user_id[:2] + "…" + user_id[-3:] if len(user_id) >= 8 else user_id[:1] + "…"


def leaderboard(conn: psycopg.Connection, limit: int = 10, include_demo: bool = False) -> list[dict[str, Any]]:
    rows = conn.execute(
        # seed_demo.py gives its invented reporters ids starting with "demo-"; they are not people.
        "SELECT user_id, sum(points) AS points FROM points_ledger WHERE (%s OR user_id NOT LIKE 'demo-%%') "
        "GROUP BY user_id ORDER BY points DESC, user_id LIMIT %s",
        (include_demo, limit),
    ).fetchall()
    return [{"user": mask(r["user_id"]), "points": r["points"]} for r in rows]


# --- community tasks -------------------------------------------------------------------

def create_task(conn: psycopg.Connection, reviewer: Reviewer, *, title: str, description: str,
                category: str, latitude: float, longitude: float, radius_m: float, target_count: int,
                reward_points: int, deadline: datetime, alert_id: UUID | None) -> dict[str, Any]:
    if reviewer.role != EXPERT:
        raise TaskError(403, "Chỉ chuyên gia hoặc cán bộ mới tạo được nhiệm vụ cộng đồng.")
    row = conn.execute(
        """
        INSERT INTO community_tasks (title, description, category, latitude, longitude, radius_m,
                                     target_count, reward_points, deadline, alert_id, created_by, is_demo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                coalesce((SELECT is_demo FROM alerts WHERE id = %s), false))
        RETURNING *
        """,
        (title, description, category, latitude, longitude, radius_m, target_count, reward_points,
         deadline, alert_id, reviewer.id, alert_id),
    ).fetchone()
    return row


def list_tasks(conn: psycopg.Connection, include_demo: bool) -> list[dict[str, Any]]:
    conn.execute("UPDATE community_tasks SET status = 'expired' WHERE status = 'open' AND deadline < now()")
    return conn.execute(
        """
        SELECT id, title, description, category, round(latitude::numeric, 4)::float AS latitude,
               round(longitude::numeric, 4)::float AS longitude, radius_m, target_count, reward_points,
               deadline, alert_id, status, completed_at, created_at, is_demo
        FROM community_tasks WHERE (is_demo = false OR %s)
        ORDER BY (status = 'open') DESC, deadline
        """,
        (include_demo,),
    ).fetchall()


def complete_task(conn: psycopg.Connection, task_id: UUID, reviewer: Reviewer) -> dict[str, Any]:
    """Done when this person sent after-photos for enough reports inside the task area."""
    task = conn.execute("SELECT * FROM community_tasks WHERE id = %s FOR UPDATE", (task_id,)).fetchone()
    if task is None:
        raise TaskError(404, "Không có nhiệm vụ này.")
    if task["status"] != "open":
        raise TaskError(409, f"Nhiệm vụ đang ở trạng thái '{task['status']}'.")
    if task["deadline"] < conn.execute("SELECT now() AS t").fetchone()["t"]:
        conn.execute("UPDATE community_tasks SET status = 'expired' WHERE id = %s", (task_id,))
        raise TaskError(409, "Nhiệm vụ đã quá hạn.")
    done = conn.execute(
        """
        SELECT count(DISTINCT t.observation_id) AS n
        FROM verification_photos p
        JOIN verification_tasks t ON t.id = p.task_id
        JOIN observations o ON o.id = t.observation_id
        WHERE p.kind = 'after' AND p.uploaded_by = %(who)s AND p.created_at >= %(since)s
          AND ST_DWithin(o.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius)s)
        """,
        {"who": reviewer.id, "since": task["created_at"], "lon": task["longitude"], "lat": task["latitude"],
         "radius": task["radius_m"]},
    ).fetchone()["n"]
    if done < task["target_count"]:
        raise TaskError(409, f"Mới có ảnh sau xử lý cho {done}/{task['target_count']} điểm trong khu vực.")
    conn.execute(
        "UPDATE community_tasks SET status = 'completed', completed_by = %s, completed_at = now() WHERE id = %s",
        (reviewer.id, task_id),
    )
    points = award(conn, reviewer.id, "task_completed", task_id, task["reward_points"])
    return {"id": task_id, "status": "completed", "sites_done": done, "points": points}
