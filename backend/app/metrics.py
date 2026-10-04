"""Dashboard metrics (plan section 21), with the plan's own formulas.

    resolution rate     = resolved alerts / all alerts
    verification rate   = verified observations / all observations
    response time       = verified_at - received_at, averaged over reviewed reports
    risk reduction      = score before - score after, on sites cleaned up

Demo rows are counted only when asked, like everywhere else in the API.
"""

from __future__ import annotations

from typing import Any

import psycopg


def compute(conn: psycopg.Connection, *, days: int, include_demo: bool) -> dict[str, Any]:
    params = {"days": days, "demo": include_demo}
    obs = conn.execute(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE observed_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Ho_Chi_Minh')
                                                       AT TIME ZONE 'Asia/Ho_Chi_Minh') AS today,
               count(*) FILTER (WHERE status = 'verified') AS verified,
               count(*) FILTER (WHERE status = 'dismissed') AS dismissed,
               count(*) FILTER (WHERE status IN ('verified', 'dismissed')) AS reviewed,
               avg(confidence) AS avg_confidence,
               count(*) FILTER (WHERE level IN ('orange', 'red') AND status <> 'dismissed') AS high_risk,
               count(*) FILTER (WHERE answers ->> 'recent_rain' IN ('within_48h', 'flood_or_heavy')) AS after_rain,
               avg(extract(epoch FROM verified_at - received_at) / 3600)
                   FILTER (WHERE verified_at IS NOT NULL) AS response_hours,
               count(*) FILTER (WHERE group_score_after IS NOT NULL) AS treated,
               avg(group_score) FILTER (WHERE group_score_after IS NOT NULL) AS score_before,
               avg(group_score_after) FILTER (WHERE group_score_after IS NOT NULL) AS score_after,
               count(*) FILTER (WHERE group_score_after < group_score) AS reduced
        FROM observations
        WHERE duplicate_of IS NULL
          AND observed_at >= now() - make_interval(days => %(days)s)
          AND (is_demo = false OR %(demo)s)
        """,
        params,
    ).fetchone()
    alerts = conn.execute(
        """
        SELECT count(*) FILTER (WHERE recent) AS total,
               count(*) FILTER (WHERE recent AND status = 'resolved') AS resolved,
               -- open alerts count whenever they were opened: they still need action
               count(*) FILTER (WHERE status IN ('open', 'verified')) AS open,
               count(*) FILTER (WHERE status IN ('open', 'verified') AND level IN ('orange', 'red')) AS open_high
        FROM (SELECT *, created_at >= now() - make_interval(days => %(days)s) AS recent FROM alerts) a
        WHERE (is_demo = false OR %(demo)s)
        """,
        params,
    ).fetchone()
    tasks = conn.execute(
        """
        SELECT count(*) FILTER (WHERE status = 'open') AS open,
               count(*) FILTER (WHERE status = 'completed') AS completed
        FROM community_tasks WHERE (is_demo = false OR %(demo)s)
        """,
        params,
    ).fetchone()
    top = conn.execute(
        """
        SELECT id, category, level, reports, reporters, max_risk,
               round(latitude::numeric, 4)::float AS latitude, round(longitude::numeric, 4)::float AS longitude
        FROM alerts WHERE status IN ('open', 'verified') AND (is_demo = false OR %(demo)s)
        ORDER BY array_position(ARRAY['red', 'orange', 'yellow', 'green'], level), max_risk DESC, reports DESC
        LIMIT 5
        """,
        params,
    ).fetchall()

    treated = conn.execute(
        """
        SELECT id, vector_group, round(latitude::numeric, 4)::float AS latitude,
               round(longitude::numeric, 4)::float AS longitude, group_score AS before,
               group_score_after AS after, treated_at
        FROM observations
        WHERE group_score_after IS NOT NULL AND duplicate_of IS NULL AND (is_demo = false OR %(demo)s)
        ORDER BY treated_at DESC LIMIT 20
        """,
        params,
    ).fetchall()
    # Reports and verified reports per Vietnamese calendar day, for the chart.
    conn.execute("SET LOCAL TIME ZONE 'Asia/Ho_Chi_Minh'")
    daily = conn.execute(
        """
        WITH days AS (
            SELECT generate_series(date_trunc('day', now()) - make_interval(days => %(days)s - 1),
                                   date_trunc('day', now()), interval '1 day') AS day
        ), counted AS (
            SELECT date_trunc('day', observed_at) AS day, count(*) AS reports,
                   count(*) FILTER (WHERE status = 'verified') AS verified
            FROM observations
            WHERE observed_at >= date_trunc('day', now()) - make_interval(days => %(days)s - 1)
              AND duplicate_of IS NULL AND (is_demo = false OR %(demo)s)
            GROUP BY 1
        )
        SELECT d.day::date AS day, coalesce(c.reports, 0) AS reports, coalesce(c.verified, 0) AS verified
        FROM days d LEFT JOIN counted c USING (day) ORDER BY d.day
        """,
        params,
    ).fetchall()

    def ratio(part, whole):
        return None if not whole else round(part / whole, 3)

    before, after = obs["score_before"], obs["score_after"]
    return {
        "days": days,
        "total_observations": obs["total"],
        "observations_today": obs["today"],
        "verified_observations": obs["verified"],
        "verification_rate": ratio(obs["verified"], obs["total"]),
        "reviewed_observations": obs["reviewed"],
        "average_confidence": None if obs["avg_confidence"] is None else round(obs["avg_confidence"], 3),
        "high_risk_locations": obs["high_risk"],
        "reports_after_rainfall": obs["after_rain"],
        "average_response_hours": None if obs["response_hours"] is None else round(float(obs["response_hours"]), 1),
        "open_alerts": alerts["open"],
        "open_high_alerts": alerts["open_high"],
        "resolved_hotspots": alerts["resolved"],
        "resolution_rate": ratio(alerts["resolved"], alerts["total"]),
        "community_tasks_open": tasks["open"],
        "community_tasks_completed": tasks["completed"],
        "treated_sites": obs["treated"],
        "sites_with_lower_risk": obs["reduced"],
        "risk_before": None if before is None else round(before, 3),
        "risk_after": None if after is None else round(after, 3),
        "risk_reduction": None if before is None else round(before - after, 3),
        "risk_reduction_pct": None if not before else round((before - after) / before * 100, 1),
        "top_areas": top,
        "treated": treated,
        "daily": daily,
    }
