"""The OneAquaHealth consortium's own data (api.enora-oah.eu), read through its open API.

The hackathon points at three OneAquaHealth tools: the Citizen Science App, the Resilience
Map and the Diptera Forecasting App. The Resilience Map's API is open, so AquaPulse reads it
and becomes the layer above it that the brief asks for:

    cities          the five pilot cities (Coimbra, Toulouse, Ghent, Benevento, Oslo)
    sites           their research sites, plus the sites people created in the Citizen
                    Science App (kind = 'citizen')
    health risks    measured at a site: pathogens, faecal pollution, antibiotic-resistance
                    genes, and their combined score
    urban context   how built-up and green the 500 m around a site is, how far the sewage works are
    weather         measured daily weather per site (fetched live, cached)

Their numbers stay theirs: they are shown as measurements from OneAquaHealth, with the
sampling date, and they never enter our citizen risk scores, hotspots or alerts. A citizen
report is only ever *linked* to the nearest site, with the distance stated.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import psycopg

SOURCE_URL = "https://api.enora-oah.eu/api"
ATTRIBUTION = ("Dữ liệu điểm quan trắc, chỉ số sức khỏe và thời tiết: OneAquaHealth "
               "(api.enora-oah.eu), dự án do Liên minh châu Âu tài trợ.")
USER_AGENT = "AquaPulse/0.1 (IEEE OneAquaHealth Hackathon 2026 entry)"
TIMEOUT = 20
WEATHER_CACHE_S = 3 * 3600
RISK_WORDS = [(0.66, "cao"), (0.33, "trung bình"), (0.0, "thấp")]
INDICATOR_LABELS = {
    "pathogen_risk": "Mầm bệnh",
    "fecal_risk": "Ô nhiễm từ phân",
    "arg_risk": "Gen kháng kháng sinh",
    "health_risk": "Chỉ số rủi ro sức khỏe tổng hợp",
}


def base_url() -> str:
    return os.environ.get("AQUAPULSE_OAH_API") or SOURCE_URL


def client(existing: httpx.Client | None = None) -> httpx.Client:
    return existing or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, base_url=base_url())


def risk_word(value: float | None) -> str:
    if value is None:
        return "chưa có"
    return next(word for floor, word in RISK_WORDS if value >= floor)


def _date(value: str | None) -> date | None:
    return datetime.fromisoformat(value).date() if value else None


# --- sync ---------------------------------------------------------------------------------

def sync(database, http: httpx.Client | None = None) -> dict[str, int]:
    """Pull cities, sites, health risks and urban context. Weather and nitrates are fetched
    per site when a page asks for them, so we do not hammer their API."""
    own = http is None
    http = client(http)
    try:
        cities = http.get("/cities/all").raise_for_status().json()
        sites = http.get("/sites/all").raise_for_status().json()
        citizen_sites = http.get("/sites/user-generated").raise_for_status().json()
        risks = http.get("/resilience-map/health-risks").raise_for_status().json()
        urban = http.get("/resilience-map/urban-parameters").raise_for_status().json()
    finally:
        if own:
            http.close()

    with database.connect() as conn:
        for city in cities:
            conn.execute(
                "INSERT INTO oah_cities (id, name, latitude, longitude) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, latitude = EXCLUDED.latitude, "
                "longitude = EXCLUDED.longitude, fetched_at = now()",
                (city["id"], city["name"], city["latitude"], city["longitude"]))
        for site in sites:
            conn.execute(
                "INSERT INTO oah_sites (code, name, city_id, kind, latitude, longitude, altitude) "
                "VALUES (%s, %s, %s, 'research', %s, %s, %s) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, city_id = EXCLUDED.city_id, "
                "kind = EXCLUDED.kind, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, "
                "altitude = EXCLUDED.altitude, fetched_at = now()",
                (site["code"], site["name"], (site.get("city") or {}).get("id"),
                 site["latitude"], site["longitude"], site.get("altitude")))
        for site in citizen_sites:
            # Sites created by people in the OneAquaHealth Citizen Science App; they carry no city.
            conn.execute(
                "INSERT INTO oah_sites (code, name, city_id, kind, latitude, longitude, altitude) "
                "VALUES (%s, %s, NULL, 'citizen', %s, %s, %s) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind, "
                "latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, fetched_at = now()",
                (site["userSiteCode"], site.get("name") or site["userSiteCode"],
                 site["latitude"], site["longitude"], site.get("altitude")))
        for row in risks:
            conn.execute(
                "INSERT INTO oah_health_risks (site_code, sampled_on, pathogen_risk, fecal_risk, arg_risk, "
                "health_risk) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (site_code, sampled_on) DO UPDATE SET pathogen_risk = EXCLUDED.pathogen_risk, "
                "fecal_risk = EXCLUDED.fecal_risk, arg_risk = EXCLUDED.arg_risk, health_risk = EXCLUDED.health_risk",
                (row["researchSiteCode"], _date(row.get("samplingDate")), row.get("scaledPathogenRisk"),
                 row.get("scaledFecalRisk"), row.get("scaledArgRisk"), row.get("healthRiskScore")))
        for row in urban:
            conn.execute(
                "INSERT INTO oah_urban_context (site_code, urban_pct_500m, impervious_pct_500m, "
                "veg_cover_frac_500m, distance_sewage_m, distance_motorway_m) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (site_code) DO UPDATE SET urban_pct_500m = EXCLUDED.urban_pct_500m, "
                "impervious_pct_500m = EXCLUDED.impervious_pct_500m, veg_cover_frac_500m = EXCLUDED.veg_cover_frac_500m, "
                "distance_sewage_m = EXCLUDED.distance_sewage_m, distance_motorway_m = EXCLUDED.distance_motorway_m",
                (row["researchSiteCode"], row.get("urbanPct500m"), row.get("imperviousPct500m"),
                 row.get("vegCoverFrac500m"), row.get("distanceToSewageStations"), row.get("distanceToMotorwayRoad")))
    return {"cities": len(cities), "sites": len(sites), "citizen_sites": len(citizen_sites),
            "health_risk_rows": len(risks), "urban_rows": len(urban)}


# --- reading ------------------------------------------------------------------------------

def cities(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT c.id, c.name, c.latitude, c.longitude,
               count(s.code) FILTER (WHERE s.kind = 'research') AS research_sites,
               round(avg(r.health_risk)::numeric, 3)::float AS avg_health_risk
        FROM oah_cities c
        LEFT JOIN oah_sites s ON s.city_id = c.id
        LEFT JOIN LATERAL (SELECT health_risk FROM oah_health_risks h WHERE h.site_code = s.code
                           ORDER BY sampled_on DESC LIMIT 1) r ON true
        GROUP BY c.id, c.name, c.latitude, c.longitude
        ORDER BY c.name
        """).fetchall()


def sites(conn: psycopg.Connection, city_id: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    """Sites with their latest health-risk sampling, as published by OneAquaHealth."""
    return conn.execute(
        """
        SELECT s.code, s.name, s.kind, s.city_id, c.name AS city_name, s.latitude, s.longitude, s.altitude,
               r.sampled_on, r.pathogen_risk, r.fecal_risk, r.arg_risk, r.health_risk,
               u.urban_pct_500m, u.impervious_pct_500m, u.veg_cover_frac_500m, u.distance_sewage_m
        FROM oah_sites s
        LEFT JOIN oah_cities c ON c.id = s.city_id
        LEFT JOIN LATERAL (SELECT * FROM oah_health_risks h WHERE h.site_code = s.code
                           ORDER BY sampled_on DESC NULLS LAST LIMIT 1) r ON true
        LEFT JOIN oah_urban_context u ON u.site_code = s.code
        WHERE (%(city)s::text IS NULL OR s.city_id = %(city)s)
          AND (%(kind)s::text IS NULL OR s.kind = %(kind)s)
        ORDER BY s.city_id NULLS LAST, s.code
        """,
        {"city": city_id, "kind": kind}).fetchall()


def site(conn: psycopg.Connection, code: str) -> dict[str, Any] | None:
    found = sites(conn, None, None)
    return next((s for s in found if s["code"] == code), None)


def nearest_site(conn: psycopg.Connection, latitude: float, longitude: float,
                 within_m: float = 50_000) -> dict[str, Any] | None:
    """The OneAquaHealth site nearest a citizen report, with the distance stated."""
    return conn.execute(
        """
        SELECT code, name, kind, city_id,
               round(ST_Distance(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography))::int AS distance_m
        FROM oah_sites
        WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(r)s)
        ORDER BY distance_m LIMIT 1
        """,
        {"lat": latitude, "lon": longitude, "r": within_m}).fetchone()


def history(conn: psycopg.Connection, code: str) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT sampled_on, pathogen_risk, fecal_risk, arg_risk, health_risk FROM oah_health_risks "
        "WHERE site_code = %s ORDER BY sampled_on", (code,)).fetchall()


# --- live endpoints (fetched when a page asks, then cached) ---------------------------------

_cache: dict[tuple[str, str], tuple[float, Any]] = {}


def _cached(key: tuple[str, str], fetch, ttl: float = WEATHER_CACHE_S):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        value = fetch()
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    _cache[key] = (time.time(), value)
    return value


def weather(code: str, days: int = 14, http: httpx.Client | None = None) -> list[dict[str, Any]] | None:
    """Daily measured weather at a OneAquaHealth site; None when their API is unreachable."""
    end = datetime.now().astimezone()
    start = end - timedelta(days=days)

    def fetch():
        own = http is None
        session = client(http)
        try:
            response = session.get("/resilience-map/weather", params={
                "siteCode": code, "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
            response.raise_for_status()
            return [{"day": row["date"], "mm": row.get("precipTotalMm"), "temp_c": row.get("t2mMeanC")}
                    for row in response.json()]
        finally:
            if own:
                session.close()

    return _cached(("weather", code), fetch)


def nitrates(code: str, http: httpx.Client | None = None) -> list[dict[str, Any]] | None:
    def fetch():
        own = http is None
        session = client(http)
        try:
            response = session.get(f"/resilience-map/health-indicators/nitrates/{code}")
            response.raise_for_status()
            return response.json().get("series", [])
        finally:
            if own:
                session.close()

    return _cached(("nitrates", code), fetch, ttl=24 * 3600)


def explain(site_row: dict[str, Any]) -> list[str]:
    """Plain sentences about their measurement, always naming the source and the date."""
    said = []
    if site_row.get("health_risk") is not None:
        when = f" (lấy mẫu {site_row['sampled_on']:%d/%m/%Y})" if site_row.get("sampled_on") else ""
        said.append(f"OneAquaHealth đo chỉ số rủi ro sức khỏe {site_row['health_risk']:.2f} tại điểm này"
                    f"{when}: mức {risk_word(site_row['health_risk'])}.")
        parts = [f"{INDICATOR_LABELS[key]} {site_row[key]:.2f}" for key in ("pathogen_risk", "fecal_risk", "arg_risk")
                 if site_row.get(key) is not None]
        if parts:
            said.append("Thành phần: " + ", ".join(parts) + ". Đây là kết quả phòng thí nghiệm của dự án, "
                        "không phải kết quả của AquaPulse.")
    else:
        said.append("Điểm này chưa có chỉ số rủi ro sức khỏe công bố.")
    if site_row.get("impervious_pct_500m") is not None:
        # Their vegetation field is named "frac" but is published as a percentage (0-89).
        said.append(f"Trong bán kính 500 m: {site_row['impervious_pct_500m']:.0f}% bề mặt bê tông hóa, "
                    f"{site_row.get('veg_cover_frac_500m') or 0:.0f}% cây xanh.")
    if site_row.get("distance_sewage_m") is not None:
        said.append(f"Trạm xử lý nước thải gần nhất cách {site_row['distance_sewage_m'] / 1000:.1f} km.")
    return said
