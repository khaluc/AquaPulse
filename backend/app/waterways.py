"""Canal segments and their "Risk Passport" (AquaPulse brief: a health record for each river stretch).

Segments come from db/data/*.geojson (canal geometry from OpenStreetMap, cut into equal
lengths) and are loaded at start-up. A report belongs to the nearest segment within
SEGMENT_RADIUS_M; reports farther from any canal stay ordinary points.

For each segment the passport gives the brief's five indices, all from our own reports:

    Eco          ecological condition from what people saw (1 = looks healthy), mean of eco_score
    Risk         signs of pollution or decline, mean group score of the reports
    Confidence   how far the data can be trusted, mean of the reports' C
    Trend        anomalous reports this week against last week (trends.classify: counts only,
                 with a significance test so three reports are not called a trend)
    Human        how much people, children in particular, are near the water

plus observation history, anomalies, life seen in the water, community participation,
rain (Open-Meteo, measured), open alerts, and plain-language explanations built by rules
from those numbers. Nothing here is a medical or laboratory conclusion.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg

from app.trends import classify

DATA_DIR = Path(__file__).resolve().parents[2] / "db" / "data"
SEGMENT_RADIUS_M = 200
ANOMALY_AT = 0.5            # a report whose group score reaches this counts as anomalous
HEAVY_RAIN_MM = 20.0        # a day with this much rain counts as heavy
DAYTIME = range(6, 18)      # local hours in which colour and sheen are visible in a photo
DAYTIME_WANTED = 3          # daytime reports wanted before an official alert, as in the brief
NIGHT_CONFIDENCE = 0.8      # a night photo shows colour and sheen poorly: its confidence counts for less
RAIN_CACHE_S = 3 * 3600
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

SIGNAL_LABELS = {
    "oil_sheen": "váng dầu", "foam": "bọt", "bad_odor": "mùi lạ", "unusual_color": "nước đổi màu",
    "floating_trash": "rác nổi", "dead_fish": "cá chết",
}


# --- segments --------------------------------------------------------------------------

def load_segments(conn: psycopg.Connection, data_dir: Path = DATA_DIR) -> int:
    """Upsert every segment found in data_dir/*.geojson. Returns how many were loaded."""
    count = 0
    for path in sorted(data_dir.glob("*.geojson")):
        for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
            p = feature["properties"]
            conn.execute(
                """
                INSERT INTO waterway_segments (id, waterway, name, seg_order, from_m, to_m, geom)
                VALUES (%s, %s, %s, %s, %s, %s, ST_GeomFromGeoJSON(%s)::geography)
                ON CONFLICT (id) DO UPDATE SET waterway = EXCLUDED.waterway, name = EXCLUDED.name,
                    seg_order = EXCLUDED.seg_order, from_m = EXCLUDED.from_m, to_m = EXCLUDED.to_m,
                    geom = EXCLUDED.geom
                """,
                (p["id"], p["waterway"], p["name"], p["order"], p["from_m"], p["to_m"],
                 json.dumps(feature["geometry"])),
            )
            count += 1
    return count


def segment_for(conn: psycopg.Connection, latitude: float, longitude: float) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, name, waterway,
               round(ST_Distance(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography))::int AS distance_m
        FROM waterway_segments
        WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(r)s)
        ORDER BY distance_m LIMIT 1
        """,
        {"lat": latitude, "lon": longitude, "r": SEGMENT_RADIUS_M},
    ).fetchone()


# Reports of the last `days` days with the segment they belong to (nearest within the radius).
_SEGMENT_REPORTS = """
    SELECT o.id, o.reporter_id, o.observed_at, o.status, o.level, o.risk, o.confidence, o.group_score,
           o.eco_score, o.human_contact_risk, o.answers, o.signals, o.vector_group, o.observation_goal,
           o.expert_required, n.segment_id,
           EXTRACT(HOUR FROM o.observed_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::int AS local_hour,
           (o.observed_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS local_day,
           EXISTS (SELECT 1 FROM verification_tasks t WHERE t.observation_id = o.id
                   AND (t.volunteer_verdict = 'confirmed' OR t.final_verdict = 'confirmed')) AS confirmed_on_site
    FROM observations o
    JOIN LATERAL (
        SELECT s.id AS segment_id FROM waterway_segments s
        WHERE ST_DWithin(s.geom, o.geom, %(r)s)
        ORDER BY ST_Distance(s.geom, o.geom) LIMIT 1
    ) n ON true
    WHERE o.duplicate_of IS NULL AND o.status <> 'dismissed'
      AND o.observed_at >= now() - make_interval(days => %(days)s)
      AND (o.is_demo = false OR %(demo)s)
"""


def _reports(conn, days: int, include_demo: bool, segment_id: str | None = None) -> list[dict[str, Any]]:
    sql = _SEGMENT_REPORTS + (" AND n.segment_id = %(seg)s" if segment_id else "") + " ORDER BY o.observed_at"
    return conn.execute(sql, {"r": SEGMENT_RADIUS_M, "days": days, "demo": include_demo, "seg": segment_id}).fetchall()


# --- rain ------------------------------------------------------------------------------

_rain_cache: dict[tuple[float, float], tuple[float, list[dict[str, Any]]]] = {}


def rain(latitude: float, longitude: float, days: int = 14, client: httpx.Client | None = None) -> list[dict[str, Any]] | None:
    """Daily rain (mm) for the last `days` days from Open-Meteo, cached; None if unreachable."""
    key = (round(latitude, 2), round(longitude, 2))
    cached = _rain_cache.get(key)
    if cached and time.time() - cached[0] < RAIN_CACHE_S:
        return cached[1]
    own = client is None
    client = client or httpx.Client(timeout=8)
    try:
        response = client.get(OPEN_METEO, params={
            "latitude": key[0], "longitude": key[1], "daily": "precipitation_sum",
            "past_days": days, "forecast_days": 1, "timezone": "Asia/Ho_Chi_Minh"})
        response.raise_for_status()
        daily = response.json()["daily"]
        series = [{"day": d, "mm": mm} for d, mm in zip(daily["time"], daily["precipitation_sum"], strict=False)
                  if mm is not None]
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    finally:
        if own:
            client.close()
    _rain_cache[key] = (time.time(), series)
    return series


# --- indices and explanations ------------------------------------------------------------

def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def _signals(answers: dict[str, Any]) -> list[str]:
    found = []
    if answers.get("oil_sheen") == "yes" or answers.get("water_color") == "rainbow_sheen":
        found.append("oil_sheen")
    if answers.get("foam") == "yes":
        found.append("foam")
    if answers.get("odor") in ("rotten", "sewage", "chemical"):
        found.append("bad_odor")
    if answers.get("water_color") in ("unusual_green", "brown_black", "milky_white"):
        found.append("unusual_color")
    if answers.get("floating_trash") in ("little", "lots"):
        found.append("floating_trash")
    if answers.get("dead_fish") == "yes":
        found.append("dead_fish")
    return found


def effective_confidence(row: dict[str, Any]) -> float | None:
    """The report's C, lowered for photos taken in the dark (the brief: "most reports were sent at night")."""
    c = row.get("confidence")
    if c is None or row.get("local_hour") is None or row["local_hour"] in DAYTIME:
        return c
    return c * NIGHT_CONFIDENCE


def confidence_label(c: float | None) -> str:
    if c is None:
        return "chưa có"
    return "cao" if c >= 0.8 else "trung bình" if c >= 0.6 else "thấp"


def _anomalous(r: dict[str, Any]) -> bool:
    return (r["group_score"] or 0) >= ANOMALY_AT


def indices(reports: list[dict[str, Any]], today: date) -> dict[str, Any]:
    week = [r for r in reports if r["local_day"] > today - timedelta(days=7)]
    before = [r for r in reports if today - timedelta(days=14) < r["local_day"] <= today - timedelta(days=7)]
    trend = classify(sum(map(_anomalous, week)), sum(map(_anomalous, before)))
    recent = week or reports
    return {
        "eco": _mean(r["eco_score"] for r in recent),
        "risk": _mean(r["group_score"] for r in recent),
        "confidence": _mean(effective_confidence(r) for r in recent),
        "confidence_label": confidence_label(_mean(effective_confidence(r) for r in recent)),
        "human_health": _mean(r["human_contact_risk"] for r in recent),
        "trend": trend.as_dict(),
        "reports_7d": len(week),
        "anomalies_7d": sum(map(_anomalous, week)),
        "anomalies_prev_7d": sum(map(_anomalous, before)),
    }


def level(reports: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> str:
    """The segment's colour: its worst open alert; else yellow for an anomaly in the last 72 h."""
    order = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
    if alerts:
        return max((a["level"] for a in alerts), key=order.__getitem__)
    if not reports:
        return "none"
    return "yellow" if any(_anomalous(r) for r in reports[-10:]) else "green"


def explain(ix: dict[str, Any], reports: list[dict[str, Any]], rain_series: list[dict[str, Any]] | None,
            alerts: list[dict[str, Any]], today: date) -> tuple[list[str], list[str]]:
    """Plain sentences about the numbers, and what to do next. Rules, not a language model."""
    sentences, actions = [], []
    week = [r for r in reports if r["local_day"] > today - timedelta(days=7)]
    t = ix["trend"]
    if t["trend"] == "insufficient_data":
        sentences.append(f"Chưa đủ dữ liệu để nói xu hướng: {ix['anomalies_7d'] + ix['anomalies_prev_7d']} "
                         "báo cáo bất thường trong 14 ngày.")
    else:
        change = round(t["increase"] * 100)
        direction = "tăng" if change > 0 else "giảm" if change < 0 else "không đổi"
        sentences.append(f"Trong 7 ngày qua, đoạn này có {ix['anomalies_7d']} báo cáo bất thường, {direction}"
                         f"{'' if change == 0 else f' {abs(change)}%'} so với 7 ngày trước ({ix['anomalies_prev_7d']}). "
                         f"{t['label']}.")
    counts = Counter(s for r in week for s in _signals(r["answers"] or {}))
    if counts:
        sentences.append("Dấu hiệu gặp nhiều nhất: " + ", ".join(
            f"{SIGNAL_LABELS[s]} ({n} lần)" for s, n in counts.most_common(3)) + ".")

    if week:
        night = sum(1 for r in week if r["local_hour"] not in DAYTIME)
        reporters = len({r["reporter_id"] for r in week if r["reporter_id"]})
        confirmed = sum(1 for r in week if r["confirmed_on_site"])
        why = []
        if night * 2 > len(week):
            why.append("phần lớn quan sát được gửi vào ban đêm, ảnh khó thấy màu nước và váng")
        if reporters < 3:
            why.append(f"chỉ {reporters} người báo")
        if not confirmed:
            why.append("chưa có ai xác minh tại hiện trường")
        label = ix["confidence_label"]
        sentences.append(f"Độ tin cậy {label}" + (f" vì {', '.join(why)}." if why and label != "cao" else "."))
        daytime = len(week) - night
        if label != "cao" and daytime < DAYTIME_WANTED:
            actions.append(f"Nên bổ sung {DAYTIME_WANTED - daytime} quan sát ban ngày trước khi phát cảnh báo "
                           "chính thức.")

    if rain_series:
        recent_rain = [d for d in rain_series if date.fromisoformat(d["day"]) > today - timedelta(days=7)]
        heavy = max(recent_rain, key=lambda d: d["mm"], default=None)
        if heavy and heavy["mm"] >= HEAVY_RAIN_MM:
            day = date.fromisoformat(heavy["day"])
            after = sum(1 for r in reports if day <= r["local_day"] <= day + timedelta(days=2))
            sentences.append(f"Mưa lớn {heavy['mm']:.0f} mm ngày {day:%d/%m} (số đo Open-Meteo); "
                             f"{after} báo cáo gửi trong 48 giờ sau đó.")
            actions.append("Sau mưa lớn, ưu tiên kiểm tra cửa xả và đoạn có báo cáo váng, mùi.")

    children = sum(1 for r in week if (r["answers"] or {}).get("contact") in ("children_nearby", "direct"))
    if children:
        sentences.append(f"{children} báo cáo có trẻ em chơi gần hoặc người tiếp xúc trực tiếp với nước.")
        if ix["anomalies_7d"]:
            actions.append("Không để trẻ chơi, lội nước ở đoạn này cho tới khi có kết quả xác minh.")
    for alert in alerts:
        if alert["status"] == "open":
            actions.append("Cần tình nguyện viên xác minh cảnh báo đang mở tại hiện trường.")
            break
    return sentences, list(dict.fromkeys(actions))


def _segment_alerts(conn, include_demo: bool) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT a.id, a.category, a.level, a.status, a.reports, a.reporters, a.evidence, a.created_at, n.segment_id
        FROM alerts a
        JOIN LATERAL (
            SELECT s.id AS segment_id FROM waterway_segments s
            WHERE ST_DWithin(s.geom, a.geom, %(r)s) ORDER BY ST_Distance(s.geom, a.geom) LIMIT 1
        ) n ON true
        WHERE a.status IN ('open', 'verified') AND (a.is_demo = false OR %(demo)s)
        """,
        {"r": SEGMENT_RADIUS_M * 2, "demo": include_demo},
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["segment_id"], []).append(row)
    return grouped


def overview(conn: psycopg.Connection, include_demo: bool) -> list[dict[str, Any]]:
    """Every segment with its indices and colour, for the map and the list."""
    today = conn.execute("SELECT (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS d").fetchone()["d"]
    segments = conn.execute(
        "SELECT id, waterway, name, seg_order, from_m, to_m, ST_AsGeoJSON(geom, 6)::json AS geometry "
        "FROM waterway_segments ORDER BY waterway, seg_order").fetchall()
    reports = _reports(conn, 14, include_demo)
    alerts = _segment_alerts(conn, include_demo)
    out = []
    for seg in segments:
        own = [r for r in reports if r["segment_id"] == seg["id"]]
        seg_alerts = alerts.get(seg["id"], [])
        out.append({**seg, "indices": indices(own, today), "level": level(own, seg_alerts),
                    "open_alerts": len(seg_alerts), "reports_14d": len(own)})
    return out


def passport(conn: psycopg.Connection, segment_id: str, include_demo: bool, with_rain: bool = True) -> dict[str, Any] | None:
    seg = conn.execute(
        "SELECT id, waterway, name, seg_order, from_m, to_m, ST_AsGeoJSON(geom, 6)::json AS geometry, "
        "ST_Y(ST_Centroid(geom::geometry)) AS lat, ST_X(ST_Centroid(geom::geometry)) AS lon "
        "FROM waterway_segments WHERE id = %s", (segment_id,)).fetchone()
    if seg is None:
        return None
    today = conn.execute("SELECT (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS d").fetchone()["d"]
    reports = _reports(conn, 30, include_demo, segment_id)
    seg_alerts = _segment_alerts(conn, include_demo).get(segment_id, [])
    rain_series = rain(seg["lat"], seg["lon"]) if with_rain else None
    ix = indices(reports, today)

    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    history = [{"day": d.isoformat(),
                "reports": sum(1 for r in reports if r["local_day"] == d),
                "anomalies": sum(1 for r in reports if r["local_day"] == d and _anomalous(r))} for d in days]
    counts = Counter(s for r in reports for s in _signals(r["answers"] or {}))
    life = [r["answers"].get("aquatic_life") for r in reports if r["answers"]]
    goals = Counter(r["observation_goal"] for r in reports if r["observation_goal"])
    sentences, actions = explain(ix, reports, rain_series, seg_alerts, today)
    return {
        "segment": {k: seg[k] for k in ("id", "waterway", "name", "seg_order", "from_m", "to_m", "geometry")},
        "level": level(reports[-30:], seg_alerts),
        "indices": ix,
        "explanation": sentences,
        "actions": actions,
        "history": history,
        "anomalies": [{"signal": s, "label": SIGNAL_LABELS[s], "count": n} for s, n in counts.most_common()],
        "life": {"seen_alive": life.count("yes"), "not_seen": life.count("no"), "asked": life.count("yes") + life.count("no"),
                 "note": "Người dân ghi nhận có hoặc không thấy cá, tôm, côn trùng sống; chưa định danh loài."},
        "participation": {
            "reports_30d": len(reports),
            "reporters": len({r["reporter_id"] for r in reports if r["reporter_id"]}),
            "confirmed_on_site": sum(1 for r in reports if r["confirmed_on_site"]),
            "goals": dict(goals),
        },
        "rain": {"source": "Open-Meteo (số đo, không phải dự báo)", "days": rain_series},
        "human_impact": {
            "index": ix["human_health"],
            "children_or_direct_contact": sum(1 for r in reports
                                              if (r["answers"] or {}).get("contact") in ("children_nearby", "direct")),
        },
        "alerts": [{**a, "id": str(a["id"])} for a in seg_alerts],
        "limits": "Chỉ số dựa trên quan sát của người dân và model ảnh; không phải kết quả xét nghiệm nước, "
                  "không kết luận nước an toàn hay độc hại.",
    }
