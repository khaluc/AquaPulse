"""The verification queue (plan section 16, flow steps W-Z).

    open --claim--> claimed --submit--> resolved                (volunteer decides)
                               \\--> escalated --resolve--> resolved   (expert decides)

A volunteer's verdict is final unless the task needs an expert (oil sheen, chemical
smell, dead animal, red alert) or the volunteer answers "unclear"; then an expert
decides. An expert may also resolve a task at any point. Nobody verifies their own
report. Every step is written to verification_events with who took it.

When a task is resolved the report becomes 'verified' or 'dismissed'; dismissed
reports drop out of hotspots and trends, and verified ones raise the reporter's
reliability for the next report (section 11).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app import community, notifications
from app.auth import EXPERT, VOLUNTEER, Reviewer
from app.errors import TaskError
from app.review import ReviewRoute

VERDICTS = ("confirmed", "not_confirmed", "unclear")
FINAL_VERDICTS = ("confirmed", "not_confirmed")


__all__ = ["TaskError"]


def log(conn: psycopg.Connection, task_id: UUID, actor: str, role: str, action: str, note: str = "") -> None:
    conn.execute(
        "INSERT INTO verification_events (task_id, actor_id, role, action, note) VALUES (%s, %s, %s, %s, %s)",
        (task_id, actor, role, action, note),
    )


def queue(conn: psycopg.Connection, observation_id: UUID, review: ReviewRoute) -> UUID:
    """Open a task for a report, or refresh the reasons on the one already open."""
    row = conn.execute(
        """
        INSERT INTO verification_tasks (observation_id, expert_required, reasons)
        VALUES (%s, %s, %s)
        ON CONFLICT (observation_id) WHERE status <> 'resolved'
        DO UPDATE SET reasons = EXCLUDED.reasons,
                      expert_required = verification_tasks.expert_required OR EXCLUDED.expert_required
        RETURNING id, (xmax = 0) AS inserted
        """,
        (observation_id, review.expert_required, review.reasons),
    ).fetchone()
    log(conn, row["id"], "system", "system", "queued" if row["inserted"] else "requeued", "; ".join(review.reasons))
    if row["inserted"]:
        where = conn.execute("SELECT latitude, longitude, is_demo FROM observations WHERE id = %s",
                             (observation_id,)).fetchone()
        notifications.task_nearby(conn, row["id"], where["latitude"], where["longitude"], review.reasons,
                                  where["is_demo"])
    return row["id"]


def list_tasks(conn: psycopg.Connection, reviewer: Reviewer, status: str | None = None) -> list[dict[str, Any]]:
    """Volunteers see open tasks and their own; experts see everything unresolved."""
    return conn.execute(
        """
        SELECT t.id, t.status, t.expert_required, t.reasons, t.assignee_id, t.volunteer_verdict,
               t.volunteer_note, t.created_at, t.claimed_at, t.submitted_at,
               o.id AS observation_id, o.latitude, o.longitude, o.observed_at, o.level, o.risk,
               o.confidence, o.image_path, o.answers,
               o.analysis -> 'vision' -> 'analysis' ->> 'explanation' AS vision_explanation
        FROM verification_tasks t JOIN observations o ON o.id = t.observation_id
        WHERE t.status <> 'resolved'
          AND (%(status)s::text IS NULL OR t.status = %(status)s)
          AND (%(role)s = 'expert' OR t.status = 'open' OR t.assignee_id = %(me)s)
          AND o.reporter_id IS DISTINCT FROM %(me)s
        ORDER BY (t.status = 'escalated') DESC, o.risk DESC, t.created_at
        """,
        {"status": status, "role": reviewer.role, "me": reviewer.id},
    ).fetchall()


def _task(conn: psycopg.Connection, task_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT t.*, o.reporter_id
        FROM verification_tasks t JOIN observations o ON o.id = t.observation_id
        WHERE t.id = %s FOR UPDATE OF t
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise TaskError(404, "Không có nhiệm vụ này.")
    return row


def _not_own_report(task: dict[str, Any], reviewer: Reviewer) -> None:
    if task["reporter_id"] is not None and task["reporter_id"] == reviewer.id:
        raise TaskError(403, "Không được tự xác minh báo cáo của chính mình.")


def _finish(conn: psycopg.Connection, task: dict[str, Any], verdict: str) -> None:
    """Close the report, reward the reporter if it was real, and tell them either way."""
    row = conn.execute(
        "UPDATE observations SET status = %s, verified_at = now() WHERE id = %s RETURNING reporter_id, is_demo",
        ("verified" if verdict == "confirmed" else "dismissed", task["observation_id"]),
    ).fetchone()
    if verdict == "confirmed":
        community.award(conn, row["reporter_id"], "report_verified", task["observation_id"])
    notifications.verification_result(conn, row["reporter_id"], task["observation_id"], verdict, row["is_demo"])


def claim(conn: psycopg.Connection, task_id: UUID, reviewer: Reviewer) -> dict[str, Any]:
    task = _task(conn, task_id)
    _not_own_report(task, reviewer)
    if task["status"] != "open":
        raise TaskError(409, f"Nhiệm vụ đang ở trạng thái '{task['status']}', không nhận được.")
    conn.execute(
        "UPDATE verification_tasks SET status = 'claimed', assignee_id = %s, claimed_at = now() WHERE id = %s",
        (reviewer.id, task_id),
    )
    log(conn, task_id, reviewer.id, reviewer.role, "claimed")
    return {"id": task_id, "status": "claimed", "assignee_id": reviewer.id}


def submit(conn: psycopg.Connection, task_id: UUID, reviewer: Reviewer, verdict: str, note: str) -> dict[str, Any]:
    """The person who claimed the task reports what they found on site."""
    if verdict not in VERDICTS:
        raise TaskError(422, f"Kết luận phải là một trong {VERDICTS}.")
    task = _task(conn, task_id)
    _not_own_report(task, reviewer)
    if task["status"] != "claimed" or task["assignee_id"] != reviewer.id:
        raise TaskError(409, "Chỉ người đã nhận nhiệm vụ mới gửi được kết luận.")
    if reviewer.role == EXPERT:
        if verdict == "unclear":
            raise TaskError(422, "Chuyên gia cần kết luận có hoặc không.")
        return resolve(conn, task_id, reviewer, verdict, note)

    escalate = task["expert_required"] or verdict == "unclear"
    conn.execute(
        """
        UPDATE verification_tasks
        SET volunteer_id = %s, volunteer_verdict = %s, volunteer_note = %s, submitted_at = now(),
            status = %s,
            final_verdict = CASE WHEN %s THEN NULL ELSE %s END,
            resolved_at = CASE WHEN %s THEN NULL ELSE now() END
        WHERE id = %s
        """,
        (reviewer.id, verdict, note, "escalated" if escalate else "resolved",
         escalate, verdict, escalate, task_id),
    )
    log(conn, task_id, reviewer.id, VOLUNTEER, f"submitted:{verdict}", note)
    community.award(conn, reviewer.id, "peer_check", task_id)
    if escalate:
        log(conn, task_id, "system", "system", "escalated",
            "Kết luận chưa rõ" if verdict == "unclear" else "Trường hợp cần chuyên gia")
        return {"id": task_id, "status": "escalated", "volunteer_verdict": verdict}
    _finish(conn, task, verdict)
    return {"id": task_id, "status": "resolved", "final_verdict": verdict}


def resolve(conn: psycopg.Connection, task_id: UUID, reviewer: Reviewer, verdict: str, note: str) -> dict[str, Any]:
    """An expert's final decision (section 16, steps K-L)."""
    if reviewer.role != EXPERT:
        raise TaskError(403, "Chỉ chuyên gia mới ra kết luận cuối.")
    if verdict not in FINAL_VERDICTS:
        raise TaskError(422, f"Kết luận cuối phải là một trong {FINAL_VERDICTS}.")
    task = _task(conn, task_id)
    _not_own_report(task, reviewer)
    if task["status"] == "resolved":
        raise TaskError(409, "Nhiệm vụ đã có kết luận cuối.")
    conn.execute(
        """
        UPDATE verification_tasks
        SET status = 'resolved', expert_id = %s, final_verdict = %s, final_note = %s, resolved_at = now()
        WHERE id = %s
        """,
        (reviewer.id, verdict, note, task_id),
    )
    log(conn, task_id, reviewer.id, EXPERT, f"resolved:{verdict}", note)
    _finish(conn, task, verdict)
    return {"id": task_id, "status": "resolved", "final_verdict": verdict}


def task_observation(conn: psycopg.Connection, task_id: UUID, reviewer: Reviewer) -> dict[str, Any]:
    """The report behind a task, for someone allowed to add on-site photos to it."""
    row = conn.execute(
        """
        SELECT t.status AS task_status, t.assignee_id, o.*
        FROM verification_tasks t JOIN observations o ON o.id = t.observation_id
        WHERE t.id = %s
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise TaskError(404, "Không có nhiệm vụ này.")
    if row["reporter_id"] is not None and row["reporter_id"] == reviewer.id:
        raise TaskError(403, "Không được tự xác minh báo cáo của chính mình.")
    if reviewer.role != EXPERT and row["assignee_id"] != reviewer.id:
        raise TaskError(403, "Chỉ người đã nhận nhiệm vụ hoặc chuyên gia mới gửi ảnh hiện trường.")
    return row


def add_photo(
    conn: psycopg.Connection, task_id: UUID, reviewer: Reviewer, kind: str,
    image_path: str, group_score: float | None, analysis: dict[str, Any],
) -> dict[str, Any]:
    """Record a before or after photo. An 'after' photo updates the report's score after."""
    row = conn.execute(
        """
        INSERT INTO verification_photos (task_id, kind, image_path, group_score, analysis, uploaded_by)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (task_id, kind, image_path, group_score, Jsonb(analysis), reviewer.id),
    ).fetchone()
    if kind == "after":
        conn.execute(
            """
            UPDATE observations SET group_score_after = %s, treated_at = now()
            WHERE id = (SELECT observation_id FROM verification_tasks WHERE id = %s)
            """,
            (group_score, task_id),
        )
        # One after-photo per site pays; more photos of the same site do not.
        community.award(conn, reviewer.id, "after_photo", task_id)
    note = "" if group_score is None else f"điểm nhóm {group_score:.2f}"
    log(conn, task_id, reviewer.id, reviewer.role, f"photo:{kind}", note)
    return {"id": row["id"], "kind": kind, "group_score": group_score}


def events(conn: psycopg.Connection, task_id: UUID) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT actor_id, role, action, note, created_at FROM verification_events WHERE task_id = %s ORDER BY id",
        (task_id,),
    ).fetchall()
