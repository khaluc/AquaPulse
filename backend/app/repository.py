"""Observation storage and the spatial queries of section 13.

The plan's hotspot query, run on test rows, had four problems:

1. It counted each report as its own neighbour, so a lone report showed
   nearby_reports = 1.
2. Only the neighbour was limited to 72 hours; a 10-day-old report still came back
   as a hotspot centre.
3. It did not filter by kind of sign, so an oil-sheen report counted towards a
   standing-water hotspot.
4. One person sending three photos from the same spot made a hotspot, and the
   hotspot came back once per report (three rows for one place).

`hotspots` uses PostGIS's ST_ClusterDBSCAN instead (flow step AA): one row per
cluster, only recent reports of the requested category, and at least
`min_reporters` different people.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

# Vietnam spans UTM zones 48N and 49N; 48N covers Hanoi and Ho Chi Minh City.
# DBSCAN in PostGIS needs a projected geometry so that eps is in metres.
CLUSTER_SRID = 32648

DUPLICATE_RADIUS_M = 100
DUPLICATE_WINDOW_HOURS = 72
DUPLICATE_MAX_HASH_BITS = 6  # dHash distance under which two photos show the same scene


@dataclass(frozen=True)
class NewObservation:
    reporter_id: str | None
    latitude: float
    longitude: float
    location_accuracy_m: float | None
    observed_at: datetime
    observation_types: list[str]
    answers: dict[str, Any]
    image_path: str
    image_sha256: str
    image_phash_hex: str
    signals: list[str]
    categories: list[str]
    risk: float
    confidence: float
    level: str
    needs_verification: bool
    analysis: dict[str, Any]
    status: str
    is_demo: bool = False
    review_reasons: list[str] = field(default_factory=list)
    expert_required: bool = False
    risk_domain: str | None = None
    vector_group: str | None = None
    group_score: float | None = None
    vector_breeding_risk: float | None = None
    environmental_signal: float | None = None
    human_contact_risk: float | None = None
    eco_score: float | None = None
    observation_goal: str | None = None


REPEATED_REPORT_RADIUS_M = 500
REPEATED_REPORT_DAYS = 7


def count_nearby_reports(
    conn: psycopg.Connection, latitude: float, longitude: float, group: str | None,
    exclude_id: UUID | None = None,
) -> int:
    """Earlier reports of the same group nearby: the Culex rule's 'repeated_reports'."""
    if group is None:
        return 0
    return conn.execute(
        """
        SELECT count(*) AS n FROM observations
        WHERE vector_group = %(group)s
          AND id IS DISTINCT FROM %(exclude)s
          AND status <> 'dismissed' AND duplicate_of IS NULL
          AND observed_at >= now() - make_interval(days => %(days)s)
          AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius)s)
        """,
        {"group": group, "days": REPEATED_REPORT_DAYS, "lon": longitude, "lat": latitude,
         "radius": REPEATED_REPORT_RADIUS_M, "exclude": exclude_id},
    ).fetchone()["n"]


# Section 11: "đã gửi nhiều báo cáo được xác minh" -> 0.8. Derived here from the
# database; a reporter's own claim about their level is never trusted.
TRUSTED_AFTER_VERIFIED = 3


def reporter_level(conn: psycopg.Connection, reporter_id: str | None, volunteers: set[str]) -> str:
    if not reporter_id:
        return "new"
    if reporter_id in volunteers:
        return "volunteer"
    verified = conn.execute(
        "SELECT count(*) AS n FROM observations WHERE reporter_id = %s AND status = 'verified'",
        (reporter_id,),
    ).fetchone()["n"]
    return "trusted" if verified >= TRUSTED_AFTER_VERIFIED else "new"


def get_observation(conn: psycopg.Connection, observation_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM observations WHERE id = %s FOR UPDATE", (observation_id,)
    ).fetchone()


def update_scoring(conn: psycopg.Connection, observation_id: UUID, item: NewObservation) -> None:
    """Store a re-scored report (the reporter confirmed or corrected their answers)."""
    conn.execute(
        """
        UPDATE observations
        SET answers = %(answers)s, observation_types = %(observation_types)s,
            signals = %(signals)s, categories = %(categories)s, risk = %(risk)s,
            confidence = %(confidence)s, level = %(level)s,
            needs_verification = %(needs_verification)s, analysis = %(analysis)s,
            status = %(status)s, review_reasons = %(review_reasons)s,
            expert_required = %(expert_required)s,
            risk_domain = %(risk_domain)s, vector_group = %(vector_group)s,
            group_score = %(group_score)s, vector_breeding_risk = %(vector_breeding_risk)s,
            environmental_signal = %(environmental_signal)s, human_contact_risk = %(human_contact_risk)s,
            eco_score = %(eco_score)s, observation_goal = %(observation_goal)s
        WHERE id = %(id)s
        """,
        {**item.__dict__, "id": observation_id,
         "answers": Jsonb(item.answers), "analysis": Jsonb(item.analysis)},
    )


def phash_bits(hex_hash: str) -> str:
    """The quality gate's 16-hex-digit dHash as a 64-character bit string for bit(64)."""
    return f"{int(hex_hash, 16):064b}"


def find_duplicate(conn: psycopg.Connection, item: NewObservation) -> UUID | None:
    """An earlier report of the same scene: same photo, or a near-identical one close by."""
    row = conn.execute(
        """
        SELECT id FROM observations
        WHERE duplicate_of IS NULL
          AND observed_at >= %(at)s - make_interval(hours => %(hours)s)
          AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius)s)
          AND (image_sha256 = %(sha)s
               OR bit_count(image_phash # %(phash)s::bit(64)) <= %(bits)s)
        ORDER BY received_at
        LIMIT 1
        """,
        {
            "at": item.observed_at, "hours": DUPLICATE_WINDOW_HOURS,
            "lon": item.longitude, "lat": item.latitude, "radius": DUPLICATE_RADIUS_M,
            "sha": item.image_sha256, "phash": phash_bits(item.image_phash_hex),
            "bits": DUPLICATE_MAX_HASH_BITS,
        },
    ).fetchone()
    return row["id"] if row else None


def insert_observation(conn: psycopg.Connection, item: NewObservation) -> tuple[UUID, UUID | None]:
    duplicate_of = find_duplicate(conn, item)
    row = conn.execute(
        """
        INSERT INTO observations (
            reporter_id, latitude, longitude, location_accuracy_m, observed_at,
            observation_types, answers, image_path, image_sha256, image_phash, duplicate_of,
            signals, categories, risk, confidence, level, needs_verification, analysis,
            status, is_demo, review_reasons, expert_required,
            risk_domain, vector_group, group_score, vector_breeding_risk,
            environmental_signal, human_contact_risk, eco_score, observation_goal)
        VALUES (
            %(reporter_id)s, %(latitude)s, %(longitude)s, %(location_accuracy_m)s, %(observed_at)s,
            %(observation_types)s, %(answers)s, %(image_path)s, %(image_sha256)s,
            %(image_phash)s::bit(64), %(duplicate_of)s,
            %(signals)s, %(categories)s, %(risk)s, %(confidence)s, %(level)s,
            %(needs_verification)s, %(analysis)s, %(status)s, %(is_demo)s,
            %(review_reasons)s, %(expert_required)s,
            %(risk_domain)s, %(vector_group)s, %(group_score)s, %(vector_breeding_risk)s,
            %(environmental_signal)s, %(human_contact_risk)s, %(eco_score)s, %(observation_goal)s)
        RETURNING id
        """,
        {
            **item.__dict__,
            "answers": Jsonb(item.answers),
            "analysis": Jsonb(item.analysis),
            "image_phash": phash_bits(item.image_phash_hex),
            "duplicate_of": duplicate_of,
        },
    ).fetchone()
    return row["id"], duplicate_of


# Recent, non-duplicate, same-category reports, each labelled with its DBSCAN cluster
# (NULL for noise, the plan's "cluster -1"). Checked against the plan's scikit-learn
# DBSCAN (haversine, eps 0.5 km, min_samples 3) on the demo data: same clusters.
_CLUSTERED = """
    WITH recent AS (
        SELECT id, reporter_id, geom, observed_at, risk, level
        FROM observations
        WHERE observed_at BETWEEN now() - make_interval(hours => %(hours)s) AND now()
          AND status <> 'dismissed'
          AND duplicate_of IS NULL
          AND %(category)s = ANY (categories)
          AND (is_demo = false OR %(include_demo)s)
    ),
    clustered AS (
        SELECT *, ST_ClusterDBSCAN(ST_Transform(geom::geometry, %(srid)s),
                                   eps => %(radius)s, minpoints => %(min_reports)s) OVER () AS cluster
        FROM recent
    )
"""


def hotspots(
    conn: psycopg.Connection,
    *,
    hours: int = 72,
    radius_m: float = 500,
    min_reports: int = 3,
    min_reporters: int = 2,
    category: str = "vector",
    include_demo: bool = False,
) -> list[dict[str, Any]]:
    """Clusters of recent, non-duplicate, same-category reports (flow steps X and AA).

    DBSCAN links reports that are within `radius_m` of a neighbour, so a cluster can be
    wider than `radius_m`; `spread_m` reports how far its reports actually reach from
    the centre.
    """
    return conn.execute(
        _CLUSTERED + """,
        summary AS (
            SELECT cluster,
                   ST_Centroid(ST_Collect(geom::geometry))::geography AS center,
                   count(*) AS reports,
                   count(DISTINCT coalesce(reporter_id, id::text)) AS reporters,
                   max(risk) AS max_risk,
                   min(observed_at) AS first_seen,
                   max(observed_at) AS last_seen,
                   array_agg(id ORDER BY observed_at) AS observation_ids,
                   ST_AsGeoJSON(ST_ConvexHull(ST_Collect(geom::geometry)), 6)::json AS hull
            FROM clustered
            WHERE cluster IS NOT NULL
            GROUP BY cluster
        )
        SELECT s.cluster, s.reports, s.reporters, s.max_risk, s.first_seen, s.last_seen,
               s.observation_ids, s.hull,
               ST_Y(s.center::geometry) AS latitude,
               ST_X(s.center::geometry) AS longitude,
               (SELECT max(ST_Distance(c.geom, s.center)) FROM clustered c WHERE c.cluster = s.cluster)
                   AS spread_m
        FROM summary s
        WHERE s.reporters >= %(min_reporters)s
        ORDER BY s.reports DESC, s.max_risk DESC
        """,
        {
            "hours": hours, "radius": radius_m, "min_reports": min_reports,
            "min_reporters": min_reporters, "category": category,
            "include_demo": include_demo, "srid": CLUSTER_SRID,
        },
    ).fetchall()


def cluster_counts(
    conn: psycopg.Connection,
    *,
    hours: int = 72,
    radius_m: float = 500,
    min_reports: int = 3,
    category: str = "vector",
    include_demo: bool = False,
) -> dict[str, int]:
    """How many reports went into the clustering, and how many were left as noise."""
    return conn.execute(
        _CLUSTERED + """
        SELECT count(*) AS reports, count(*) FILTER (WHERE cluster IS NULL) AS unclustered
        FROM clustered
        """,
        {
            "hours": hours, "radius": radius_m, "min_reports": min_reports, "category": category,
            "include_demo": include_demo, "srid": CLUSTER_SRID,
        },
    ).fetchone()


def daily_counts(
    conn: psycopg.Connection,
    *,
    days: int,
    category: str = "vector",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_m: float = 1000,
    include_demo: bool = False,
) -> list[dict[str, Any]]:
    """Reports per local calendar day for the last 2 x `days` days, oldest first.

    Days are Vietnamese days: counted in UTC, a report at 06:00 would land on the
    previous day. Optionally limited to `radius_m` around a point (one hotspot).
    """
    conn.execute("SET LOCAL TIME ZONE 'Asia/Ho_Chi_Minh'")
    return conn.execute(
        """
        WITH days AS (
            SELECT generate_series(
                date_trunc('day', now()) - make_interval(days => 2 * %(days)s - 1),
                date_trunc('day', now()),
                interval '1 day') AS day
        ),
        counted AS (
            SELECT date_trunc('day', observed_at) AS day, count(*) AS reports
            FROM observations
            WHERE observed_at >= date_trunc('day', now()) - make_interval(days => 2 * %(days)s - 1)
              AND observed_at <= now()
              AND duplicate_of IS NULL
              AND status <> 'dismissed'
              AND %(category)s = ANY (categories)
              AND (is_demo = false OR %(include_demo)s)
              AND (%(lat)s::float8 IS NULL OR ST_DWithin(
                    geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius)s))
            GROUP BY 1
        )
        SELECT d.day::date AS day, coalesce(c.reports, 0) AS reports
        FROM days d LEFT JOIN counted c USING (day)
        ORDER BY d.day
        """,
        {"days": days, "category": category, "include_demo": include_demo,
         "lat": latitude, "lon": longitude, "radius": radius_m},
    ).fetchall()


def dashboard_points(conn: psycopg.Connection, *, hours: int, include_demo: bool) -> list[dict[str, Any]]:
    """Everything the dashboard maps: one row per non-duplicate report in the window."""
    return conn.execute(
        """
        SELECT id, latitude, longitude, observed_at, vector_group, risk_domain,
               group_score, group_score_after, treated_at, vector_breeding_risk,
               environmental_signal, human_contact_risk, confidence, risk, level, status,
               expert_required, signals, is_demo,
               analysis -> 'vector_watch' ->> 'statement' AS statement
        FROM observations
        WHERE observed_at >= now() - make_interval(hours => %(hours)s)
          AND duplicate_of IS NULL
          AND (is_demo = false OR %(include_demo)s)
        ORDER BY observed_at DESC
        """,
        {"hours": hours, "include_demo": include_demo},
    ).fetchall()


def recent_observations(
    conn: psycopg.Connection, *, hours: int = 72, limit: int = 500, include_demo: bool = False
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, round(latitude::numeric, 4)::float AS latitude,
               round(longitude::numeric, 4)::float AS longitude, observed_at, level, risk, confidence, status,
               categories, signals, duplicate_of, is_demo
        FROM observations
        WHERE observed_at >= now() - make_interval(hours => %(hours)s)
          AND (is_demo = false OR %(include_demo)s)
        ORDER BY observed_at DESC
        LIMIT %(limit)s
        """,
        {"hours": hours, "limit": limit, "include_demo": include_demo},
    ).fetchall()


def map_points(conn: psycopg.Connection, *, hours: int, include_demo: bool,
               precision: int = 3) -> list[dict[str, Any]]:
    """Public map: coarse position, no reporter, plus how many reports are around each one.

    Positions are rounded (3 decimals, about 110 m) so a point does not mark someone's
    door (section 22); hotspots are computed from the exact positions server-side.
    """
    return conn.execute(
        """
        SELECT o.id, round(o.latitude::numeric, %(p)s)::float AS latitude,
               round(o.longitude::numeric, %(p)s)::float AS longitude,
               o.observed_at, o.vector_group, o.level, o.risk, o.confidence, o.status,
               o.group_score, o.group_score_after, o.is_demo,
               (SELECT count(*) FROM observations n
                 WHERE n.id <> o.id AND n.duplicate_of IS NULL AND n.status <> 'dismissed'
                   AND n.observed_at >= o.observed_at - interval '72 hours'
                   AND n.observed_at <= o.observed_at + interval '72 hours'
                   AND ST_DWithin(n.geom, o.geom, 500)
                   AND (n.is_demo = false OR %(demo)s)) AS nearby_reports
        FROM observations o
        WHERE o.observed_at >= now() - make_interval(hours => %(hours)s)
          AND o.duplicate_of IS NULL AND o.status <> 'dismissed'
          AND (o.is_demo = false OR %(demo)s)
        ORDER BY o.observed_at DESC
        LIMIT 2000
        """,
        {"hours": hours, "demo": include_demo, "p": precision},
    ).fetchall()
