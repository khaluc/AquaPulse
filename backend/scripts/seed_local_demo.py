"""Create a local-only demo in aquapulse_demo; no production data is changed.

Run from the repository root: backend/.venv/Scripts/python.exe backend/scripts/seed_local_demo.py
Every generated observation is marked is_demo. Photos and vision descriptions are simulated;
the application's real scoring, verification, community and alert code produces the results.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import DEFAULT_URL, Database

PREFIX = "demo-local-"
DATABASE_NAME = "aquapulse_demo"
PROFILE = ROOT / ".env.local-demo"
PHOTO_DIR = ROOT / "backend" / "storage" / "local-demo"
VN = timedelta(hours=7)


def local_database(source_url: str) -> str:
    """Reject remote connections before creating, migrating or deleting anything."""
    info = conninfo_to_dict(source_url)
    if (info.get("host") not in ("localhost", "127.0.0.1", "::1")
            or info.get("hostaddr", "127.0.0.1") not in ("127.0.0.1", "::1")):
        raise ValueError("Local demo requires a database on localhost.")
    info["dbname"] = DATABASE_NAME
    return make_conninfo(**info)


def configure() -> tuple[Database, Database]:
    source_url = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    source_url = source_url or DEFAULT_URL
    demo_url = local_database(source_url)
    with psycopg.connect(source_url, autocommit=True, connect_timeout=5) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE_NAME,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE_NAME)))
    config = {
        "DATABASE_URL": demo_url,
        "AQUAPULSE_PHOTO_DIR": PHOTO_DIR.as_posix(),
        "AQUAPULSE_REVIEWERS": (
            "volunteer:demo-local-vol-01:local-demo-volunteer,expert:demo-local-expert:local-demo-expert"
        ),
        "AQUAPULSE_VISION_PROVIDER": "kimi",
        "AQUAPULSE_VISION_ENABLED": "1",
        "AQUAPULSE_OAH_SYNC_HOURS": "0",
        "AQUAPULSE_PRESS_SYNC_HOURS": "0",
    }
    os.environ.update(config)
    PROFILE.write_text(
        "# Local demo only. Launch with backend/scripts/run_local_demo.py.\n"
        + "\n".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in config.items()) + "\n",
        encoding="utf-8",
    )
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    demo = Database(demo_url)
    demo.migrate()
    return demo, Database(source_url)


def copy_reference_data(source: Database, target: Database) -> None:
    """Copy already-cached real reference data, not invented laboratory measurements."""
    tables = {
        "oah_cities": "id name latitude longitude fetched_at",
        "oah_sites": "code name city_id kind latitude longitude altitude fetched_at",
        "oah_health_risks": "site_code sampled_on pathogen_risk fecal_risk arg_risk health_risk",
        "oah_urban_context": (
            "site_code urban_pct_500m impervious_pct_500m veg_cover_frac_500m "
            "distance_sewage_m distance_motorway_m"
        ),
        "press_mentions": "url title source published_at waterway tags query fetched_at",
    }
    with source.connect() as original, target.connect() as demo:
        for table, column_list in tables.items():
            columns = column_list.split()
            names = sql.SQL(", ").join(map(sql.Identifier, columns))
            if not original.execute("SELECT to_regclass(%s) AS table_name", (table,)).fetchone()["table_name"]:
                continue
            rows = original.execute(sql.SQL("SELECT {} FROM {}").format(names, sql.Identifier(table))).fetchall()
            insert = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                sql.Identifier(table), names, sql.SQL(", ").join(sql.Placeholder() for _ in columns))
            with demo.cursor() as cursor:
                cursor.executemany(insert, [tuple(row[column] for column in columns) for row in rows])
            print(f"Reference cache: {table}: {len(rows)} rows", flush=True)


async def seed(database: Database, per_segment: int, per_group: int) -> None:
    import seed_city_demo as city
    import seed_river_demo as river
    from app import alerts, community, notifications, verification, waterways
    from app.auth import EXPERT, VOLUNTEER, Reviewer
    from app.detector import load_default_detector
    from app.fusion import ObservationGroup, ReportAnswers
    from app.main import scored_observation
    from app.pipeline import run_pipeline
    from app.quality import check_image
    from app.repository import insert_observation
    from app.storage import save_photo
    from app.vector_watch import CATALOG, COMMON_QUESTIONS, QUESTIONS

    rng = random.Random(20261004)
    now = datetime.now(UTC)
    expert = Reviewer(PREFIX + "expert", EXPERT)
    volunteers = [Reviewer(PREFIX + f"vol-{i:02}", VOLUNTEER) for i in range(1, 6)]
    state = SimpleNamespace(detector=load_default_detector(), water=None, vision=river.SimulatedVision())
    with database.connect() as conn:
        waterways.load_segments(conn)
        # Only synthetic rows in the dedicated local database are replaced on a rerun.
        conn.execute("DELETE FROM observations WHERE is_demo AND reporter_id LIKE %s", (PREFIX + "%",))
        conn.execute("DELETE FROM community_tasks WHERE is_demo AND created_by = %s", (expert.id,))
        conn.execute("DELETE FROM alerts WHERE is_demo")
        conn.execute("DELETE FROM notifications WHERE is_demo")
        conn.execute("DELETE FROM points_ledger WHERE user_id LIKE %s", (PREFIX + "%",))

    segments = [(path.stem, i + 1, feature["properties"]["name"])
                for path in sorted(waterways.DATA_DIR.glob("*.geojson"))
                for i, feature in enumerate(json.loads(path.read_text(encoding="utf-8"))["features"])]
    missions = []
    with database.connect() as conn:
        for index, (slug, segment, name) in enumerate(segments):
            if index % 3 == 2:
                continue
            latitude, longitude = city.point_on(slug, segment, 0.5, 0)
            target_count = 1 if index % 3 == 0 else 2
            mission = community.create_task(
                conn, expert, title=f"[DEMO] Khảo sát và dọn rác ({slug}): {name}",
                description=f"Dữ liệu mẫu local: kiểm tra {target_count} điểm, chụp ảnh trước/sau, ghi nhận màu nước và mùi.",
                category="water_quality", latitude=latitude, longitude=longitude, radius_m=900,
                target_count=target_count, reward_points=80 + index % 5 * 20,
                deadline=now + timedelta(days=-2 if index % 7 == 0 else 3 + index % 10), alert_id=None)
            conn.execute("UPDATE community_tasks SET is_demo = true, created_at = %s WHERE id = %s",
                         (now - timedelta(days=35), mission["id"]))
            missions.append((index, mission))

    generated = []
    day_offsets = [0, 0, 1, 1, 2, 4, 11, 24]
    river_answers = [city.CLEAN, city.LITTER, city.BLACK_WATER, city.FOAMY, city.DEAD_FISH,
                     {**river.OILY, "contact": "children_nearby"}]
    serial = 0

    async def observation(group, answers, latitude, longitude, observed, scenario):
        nonlocal serial
        serial += 1
        picture = river.drawn_photo(serial * 7919, bool(answers.get("oil_sheen") == "yes"),
                                    rng.randint(1, 18), answers.get("water_color") == "brown_black")
        quality = check_image(picture)
        state.vision.sheen = answers.get("oil_sheen") == "yes"
        report = ReportAnswers.model_validate({**answers, "observation_group": group})
        result = await run_pipeline(state, picture, report, quality, conf_floor=0.05, with_water=False,
                                    with_vision=True, with_detector=group in (
                                        "aedes_breeding_risk", "culex_environmental_risk", "mosquito_activity"))
        stored = save_photo(picture)
        reporter = PREFIX + f"resident-{serial % 40 + 1:02}"
        item = scored_observation(result, reporter_id=reporter, latitude=latitude, longitude=longitude,
                                  location_accuracy_m=rng.randint(5, 35), observed_at=observed,
                                  image_path=stored.relative_path, image_sha256=stored.sha256,
                                  image_phash_hex=str(quality.metrics["phash"]), is_demo=True)
        with database.connect() as conn:
            observation_id, duplicate = insert_observation(conn, item)
            conn.execute("UPDATE observations SET received_at = %s WHERE id = %s",
                         (observed + timedelta(minutes=2), observation_id))
            community.award_report(conn, reporter, observation_id, duplicate is not None)
            conn.execute("UPDATE points_ledger SET created_at = %s WHERE ref_id = %s",
                         (observed + timedelta(minutes=2), str(observation_id)))
            task_id = None
            if result.review.decision == "verify" and duplicate is None:
                task_id = verification.queue(conn, observation_id, result.review)
                conn.execute("UPDATE verification_tasks SET created_at = %s WHERE id = %s",
                             (observed + timedelta(minutes=5), task_id))
        generated.append((observation_id, task_id, observed, result.vector_watch.group_score, scenario))
        if serial % 50 == 0:
            print(f"Generated {serial} observations...", flush=True)

    print(f"Seeding {len(segments)} canal segments...", flush=True)
    for index, (slug, segment, _name) in enumerate(segments):
        for n in range(per_segment):
            days = day_offsets[n % len(day_offsets)] + n // len(day_offsets) * 7
            # Several recent reports share a small area; older ones follow the same stretch.
            fraction = 0.5 + (n % 5 - 2) * 0.012
            latitude, longitude = city.point_on(slug, segment, fraction, rng.uniform(5, 22))
            pattern = index % len(river_answers) if n < 6 else (index + n) % len(river_answers)
            answers = {**river_answers[pattern], "observation_goal": [
                "environment", "biodiversity", "child_health", "flooding"][n % 4]}
            observed = now - timedelta(days=days, minutes=30 + n * 13)
            await observation("river_health", answers, latitude, longitude, observed, index)

    print("Seeding every remaining observation group...", flush=True)
    for index, (group, spec) in enumerate(CATALOG.items()):
        if group == ObservationGroup.RIVER_HEALTH:
            continue
        for n in range(per_group):
            answers = {}
            for field in (*spec.questions, *COMMON_QUESTIONS):
                options = [value for value, _label in QUESTIONS[field]["options"]
                           if value not in ("unknown", "unsure")]
                answers[field] = options[(n + index) % len(options)]
            # Recent groups form useful sanitation/vector hotspots instead of only isolated points.
            if n < 6:
                answers.update(organic_waste="yes", recent_rain="within_48h", nearby_place="home",
                               contact="children_nearby", density="many", water_stagnant="yes",
                               odor="rotten", leaf_litter="yes", standing_days="gt_7")
            latitude = 10.735 + index % 5 * 0.024 + (n % 3) * 0.0003
            longitude = 106.62 + index // 5 * 0.066 + (n % 3) * 0.00025
            days = day_offsets[n % len(day_offsets)] + n // len(day_offsets) * 4
            await observation(group.value, answers, latitude, longitude,
                              now - timedelta(days=days, minutes=15 + 9 * n), len(segments) + index)

    print("Adding volunteer work, expert decisions and before/after photos...", flush=True)
    for index, (observation_id, task_id, observed, score, scenario) in enumerate(generated):
        if task_id is None or index % 6 == 0:
            continue
        volunteer = volunteers[scenario % len(volunteers)]
        handled = min(observed + timedelta(hours=2 + index % 18), now - timedelta(minutes=2))
        with database.connect() as conn:
            verification.claim(conn, task_id, volunteer)
            conn.execute("UPDATE verification_tasks SET claimed_at = %s WHERE id = %s", (handled, task_id))
            if index % 6 == 1:
                continue
            if index % 6 == 2:
                verification.submit(conn, task_id, volunteer, "unclear", "[DEMO] Cần chuyên gia kiểm tra thêm.")
            else:
                if index % 6 == 3 and score is not None:
                    before = save_photo(river.drawn_photo(index + 100000, False, 12, True))
                    after = save_photo(river.drawn_photo(index + 200000, False, 0, False))
                    for kind, photo, value in (("before", before, score), ("after", after, min(score, 0.18))):
                        verification.add_photo(conn, task_id, volunteer, kind, photo.relative_path,
                                               value, {"note": "Ảnh mẫu demo local, mô phỏng xử lý."})
                    conn.execute("UPDATE observations SET treated_at = %s WHERE id = %s", (handled, observation_id))
                    conn.execute("UPDATE verification_photos SET created_at = %s WHERE task_id = %s",
                                 (handled, task_id))
                verdict = "not_confirmed" if index % 6 == 5 else "confirmed"
                submitted = verification.submit(conn, task_id, volunteer, verdict,
                                                "[DEMO] Kết quả khảo sát mẫu tại hiện trường.")
                if submitted["status"] == "escalated":
                    verification.resolve(conn, task_id, expert, verdict, "[DEMO] Chuyên gia kiểm tra mẫu.")
                conn.execute("UPDATE observations SET verified_at = %s WHERE id = %s", (handled, observation_id))
            conn.execute("UPDATE verification_tasks SET submitted_at = %s, "
                         "resolved_at = CASE WHEN status = 'resolved' THEN %s END WHERE id = %s",
                         (handled, handled, task_id))
            conn.execute("UPDATE verification_events SET created_at = %s WHERE task_id = %s", (handled, task_id))

    print("Refreshing alerts and community missions...", flush=True)
    with database.connect() as conn:
        alerts.refresh(conn)
        rows = conn.execute("SELECT id FROM alerts WHERE is_demo ORDER BY category, latitude").fetchall()
        for index, row in enumerate(rows):
            if index % 5 == 1:
                alerts.verify(conn, row["id"], expert, "verified", "[DEMO] Đã xác minh tại hiện trường.")
            elif index % 5 == 2:
                alerts.verify(conn, row["id"], expert, "resolved", "[DEMO] Đã thu gom rác, xử lý vật chứa.")
        completed = 0
        for index, mission in missions:
            if mission["deadline"] <= now:
                continue
            for volunteer in volunteers:
                done = conn.execute(
                    "SELECT count(DISTINCT t.observation_id) AS n FROM verification_photos p "
                    "JOIN verification_tasks t ON t.id = p.task_id "
                    "JOIN observations o ON o.id = t.observation_id "
                    "WHERE p.kind = 'after' AND p.uploaded_by = %s AND "
                    "ST_DWithin(o.geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)",
                    (volunteer.id, mission["longitude"], mission["latitude"], mission["radius_m"])).fetchone()["n"]
                if done >= mission["target_count"] and index % 3 == 0:
                    community.complete_task(conn, mission["id"], volunteer)
                    completed += 1
                    break
            notifications._store(
                conn, "task_nearby", f"[DEMO] Nhiệm vụ cộng đồng: {mission['title']}",
                latitude=mission["latitude"], longitude=mission["longitude"], ref_id=str(mission["id"]), is_demo=True)
        community.list_tasks(conn, include_demo=True)
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM observations WHERE is_demo) AS observations, "
            "(SELECT count(DISTINCT vector_group) FROM observations WHERE is_demo) AS groups, "
            "(SELECT count(*) FROM observations WHERE is_demo AND status = 'verified') AS verified, "
            "(SELECT count(*) FROM observations WHERE is_demo AND group_score_after IS NOT NULL) AS treated, "
            "(SELECT count(*) FROM verification_tasks) AS verification_tasks, "
            "(SELECT count(*) FROM alerts WHERE is_demo) AS alerts, "
            "(SELECT count(*) FROM community_tasks WHERE is_demo) AS missions, "
            "(SELECT count(*) FROM notifications WHERE is_demo) AS notifications, "
            "(SELECT count(DISTINCT user_id) FROM points_ledger WHERE user_id LIKE 'demo-local-%') AS people"
        ).fetchone()
        print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)
        print(f"Completed missions: {completed}", flush=True)
        duplicates = conn.execute("SELECT count(*) AS n FROM observations WHERE is_demo "
                                  "AND duplicate_of IS NOT NULL").fetchone()["n"]
        print(f"Duplicate photos: {duplicates}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-segment", type=int, default=8)
    parser.add_argument("--per-group", type=int, default=12)
    parser.add_argument("--sync-reference", action="store_true", help="Fetch real OneAquaHealth/news reference data")
    args = parser.parse_args()
    if args.per_segment < 6 or args.per_group < 6:
        parser.error("Use at least 6 observations per segment/group.")
    database, source = configure()
    print(f"Local-only database: {DATABASE_NAME}", flush=True)
    copy_reference_data(source, database)
    await seed(database, args.per_segment, args.per_group)
    if args.sync_reference:
        from app import oneaqua, press

        for name, sync in (("OneAquaHealth", oneaqua.sync), ("Press", press.sync)):
            try:
                print(f"{name}: {sync(database)}", flush=True)
            except (httpx.HTTPError, OSError, ValueError) as exc:
                print(f"{name}: sync unavailable ({type(exc).__name__}); cached data retained.", flush=True)
    print("Open http://localhost:8008/?demo=1 after running backend/scripts/run_local_demo.py", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
