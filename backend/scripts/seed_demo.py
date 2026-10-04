"""Fill the database with demo observations for the hotspot map, trends and dashboard.

Photos are real test-split images run through the real pipeline; the locations,
reporters and answers are invented, and every row is stored with is_demo = true.
The API hides demo rows unless asked with ?include_demo=true.

The scenarios follow the Vector Watch demo script: water-filled containers in one
alley, a fly cluster around organic waste about 300 m away, unusual water in a canal,
rats near a market, and one site that was verified and cleaned up (with an after
photo). The fly, water and rat reports rest on the reporters' answers: there is no
trained model for those groups yet.

Alerts are refreshed after every report, as the API does, so alerts open (and send
their notices) as the reports come in. Reporters get their report points, and a
community mission "Kiểm tra 3 điểm nước đọng sau mưa" is opened on the Q.10 alert.

    python scripts/seed_demo.py           # from backend/, with docker compose up -d db
    python scripts/seed_demo.py --clear   # remove earlier demo rows first
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import alerts, community, repository, verification
from app.auth import EXPERT, Reviewer
from app.db import load_default_database
from app.detector import REPO_ROOT, load_default_detector, load_image
from app.fusion import ReportAnswers
from app.main import scored_observation
from app.pipeline import run_pipeline
from app.quality import check_image
from app.storage import save_photo
from app.water import load_default_segmenter

DEG_PER_M = 1 / 111_320
DEMO_EXPERT = Reviewer("demo-expert", EXPERT)


def aedes(rng):
    return {"observation_group": "aedes_breeding_risk", "water_stagnant": "yes",
            "container_type": rng.choice(["flower_pot", "bucket_or_jar", "plastic_box"]),
            "leaf_litter": rng.choice(["yes", "no"]), "standing_days": rng.choice(["d4_7", "gt_7"]),
            "nearby_place": rng.choice(["home", "school"]), "contact": rng.choice(["passing", "children_nearby"]),
            "recent_rain": "within_48h"}


def flies(rng):
    return {"observation_group": "fly_cluster", "density": rng.choice(["some", "many"]),
            "organic_waste": "yes", "dead_animal_or_feces": rng.choice(["yes", "no"]),
            "odor": "rotten", "near_food_place": "yes", "nearby_place": "home", "contact": "passing",
            "recent_rain": "within_48h"}


def water_anomaly(rng):
    return {"observation_group": "water_quality_signal",
            "water_color": rng.choice(["brown_black", "rainbow_sheen", "unusual_green"]),
            "foam": rng.choice(["yes", "no"]), "odor": rng.choice(["sewage", "chemical"]),
            "dead_fish_or_animal_contact": "no", "nearby_place": "home", "contact": "passing",
            "recent_rain": "within_48h"}


def rats(rng):
    return {"observation_group": "rodent_sighting", "density": rng.choice(["few", "some"]),
            "seen_where": "near_drain", "organic_waste": "yes", "nearby_place": "home", "contact": "passing"}


# (name, latitude, longitude, reports, reporters, spread in m, hours ago, answers, photo pool)
SCENARIOS = [
    ("Hẻm Q.10, vật chứa có nước", 10.7626, 106.6602, 4, 4, 180, (1, 48), aedes, "water"),
    ("Q.10, ruồi quanh bãi rác cách ~300 m", 10.7653, 106.6602, 3, 3, 120, (1, 40), flies, "detect"),
    ("Kênh Nhiêu Lộc, nước bất thường", 10.7880, 106.6860, 3, 3, 200, (2, 60), water_anomaly, "detect"),
    ("Chợ Bà Chiểu, chuột gần cống", 10.8030, 106.6990, 2, 2, 80, (3, 30), rats, "detect"),
    ("Chợ Bình Thạnh, vật chứa có nước", 10.8016, 106.7109, 3, 3, 250, (1, 48), aedes, "water"),
    ("Một người gửi 3 ảnh, không thành điểm nóng", 10.7769, 106.7009, 3, 1, 40, (1, 48), aedes, "water"),
    ("Báo cáo lẻ ở Thủ Đức", 10.8494, 106.7537, 1, 1, 0, (1, 48), aedes, "water"),
    # Section 15's trend example for the Binh Thanh market: 4 last week, 9 this week.
    ("Bình Thạnh, đầu tuần này", 10.8016, 106.7109, 6, 6, 400, (72, 24 * 6), aedes, "detect"),
    ("Bình Thạnh, tuần trước", 10.8016, 106.7109, 4, 4, 400, (24 * 8, 24 * 13), aedes, "detect"),
]


def photo_pools() -> dict[str, list[Path]]:
    """Every row needs its own photo, or the duplicate check would (rightly) drop it."""
    return {
        "water": sorted((REPO_ROOT / "data" / "water_seg" / "images" / "test").glob("vistext_*.jpg")),
        "detect": sorted((REPO_ROOT / "data" / "images" / "test").glob("vistext_*.jpg")),
    }


async def score_photo(state, path: Path, answers: ReportAnswers):
    picture = load_image(path.read_bytes())
    quality = check_image(picture)
    if not quality.usable:
        return None
    result = await run_pipeline(state, picture, answers, quality, conf_floor=0.05, with_water=True, with_vision=False)
    return picture, quality, result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="delete earlier demo rows first")
    args = parser.parse_args()

    database = load_default_database()
    if database is None:
        sys.exit("Database not reachable. Run: docker compose up -d db")
    if args.clear:
        with database.connect() as conn:
            deleted = conn.execute("DELETE FROM observations WHERE is_demo").rowcount
            conn.execute("DELETE FROM community_tasks WHERE is_demo")
            conn.execute("DELETE FROM alerts WHERE is_demo")
            conn.execute("DELETE FROM notifications WHERE is_demo")
            conn.execute("DELETE FROM points_ledger WHERE user_id LIKE 'demo-%'")
        print(f"deleted {deleted} earlier demo rows, with their alerts, missions, notices and points")

    state = SimpleNamespace(detector=load_default_detector(), water=load_default_segmenter(), vision=None)
    rng = random.Random(42)
    pools = photo_pools()
    used = dict.fromkeys(pools, 0)
    now = datetime.now(UTC)
    clean_up_task = None

    for index, (name, lat, lon, reports, reporters, spread, (newest, oldest), make_answers, pool) in enumerate(SCENARIOS):
        print(f"\n# {name}")
        for i in range(reports):
            path = pools[pool][used[pool] % len(pools[pool])]
            used[pool] += 1
            answers = ReportAnswers.model_validate(make_answers(rng))
            scored = await score_photo(state, path, answers)
            if scored is None:
                print(f"  skip {path.name}: quality gate")
                continue
            picture, quality, result = scored
            stored = save_photo(picture)
            item = scored_observation(
                result,
                reporter_id=f"demo-{index}-{i % reporters}",
                latitude=lat + rng.uniform(-spread, spread) * DEG_PER_M,
                longitude=lon + rng.uniform(-spread, spread) * DEG_PER_M,
                location_accuracy_m=rng.uniform(5, 30),
                observed_at=now - timedelta(hours=rng.uniform(newest, oldest)),
                image_path=stored.relative_path,
                image_sha256=stored.sha256,
                image_phash_hex=str(quality.metrics["phash"]),
                is_demo=True,
            )
            with database.connect() as conn:
                observation_id, duplicate_of = repository.insert_observation(conn, item)
                task = (verification.queue(conn, observation_id, result.review)
                        if result.review.decision == "verify" else None)
                community.award_report(conn, item.reporter_id, observation_id, duplicate_of is not None)
                for change in alerts.refresh(conn):
                    print(f"  cảnh báo {change['change']}: mức {change['level']}")
            if clean_up_task is None and task is not None and name.startswith("Hẻm Q.10"):
                clean_up_task = task
            watch = result.vector_watch
            group_score = "-" if watch.group_score is None else f"{watch.group_score:.2f}"
            print(f"  {watch.group.value:22s} điểm nhóm {group_score:4s}  R={result.assessment.risk:.2f} "
                  f"-> {result.review.decision}")

    if clean_up_task is not None:
        await verified_clean_up(database, state, clean_up_task, pools["detect"][-1])
    open_mission(database, now)


def open_mission(database, now: datetime) -> None:
    """Section 19's demo mission, on the Q.10 alert."""
    with database.connect() as conn:
        alerts.refresh(conn)  # the clean-up changed which reports count
        alert = conn.execute(
            """
            SELECT id, latitude, longitude FROM alerts
            WHERE is_demo AND category = 'vector' AND status IN ('open', 'verified')
            ORDER BY ST_Distance(geom, ST_SetSRID(ST_MakePoint(106.6602, 10.7626), 4326)::geography)
            LIMIT 1
            """
        ).fetchone()
        if alert is None:
            print("\nno Q.10 alert: mission not created")
            return
        community.create_task(
            conn, DEMO_EXPERT, title="Kiểm tra 3 điểm nước đọng sau mưa",
            description="Sau mưa, kiểm tra vật chứa có đọng nước quanh hẻm, đổ nước hoặc úp ngược, chụp ảnh sau xử lý.",
            category="vector", latitude=alert["latitude"], longitude=alert["longitude"], radius_m=500,
            target_count=3, reward_points=100, deadline=now + timedelta(hours=24), alert_id=alert["id"])
    print("\n# Nhiệm vụ cộng đồng: Kiểm tra 3 điểm nước đọng sau mưa (24 giờ, 100 điểm)")


async def verified_clean_up(database, state, task_id, after_photo: Path) -> None:
    """One Q.10 site: an expert confirms it, then an 'after' photo shows the water gone."""
    print("\n# Q.10: xác minh và ảnh sau xử lý")
    with database.connect() as conn:
        row = verification.task_observation(conn, task_id, DEMO_EXPERT)
        verification.resolve(conn, task_id, DEMO_EXPERT, "confirmed", "Đã thấy nước đọng trong chậu, đã đổ bỏ.")
    after_answers = ReportAnswers.model_validate({**row["answers"], "water_stagnant": "no", "leaf_litter": "no"})
    scored = await score_photo(state, after_photo, after_answers)
    if scored is None:
        print("  after photo failed the quality gate")
        return
    picture, _, result = scored
    stored = save_photo(picture)
    with database.connect() as conn:
        verification.add_photo(conn, task_id, DEMO_EXPERT, "after", stored.relative_path,
                               result.vector_watch.group_score, result.payload)
    print(f"  điểm nhóm trước {row['group_score']:.2f} -> sau xử lý {result.vector_watch.group_score:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
