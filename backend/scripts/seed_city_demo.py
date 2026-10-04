"""Sample data for the whole city: every canal system, plus the mosquito and sanitation groups.

seed_river_demo.py tells one story on one stretch. This fills the map around it, so the pages
show what a month of a running pilot would look like:

    * observations along all eight canal systems, day and night, over three weeks;
    * three more clusters that open alerts - black water, dead fish, foam - each at a
      different stage: open, confirmed on site, resolved;
    * standing-water and fly reports away from the canals, so the dashboard's other layers
      and its before/after chart have something in them;
    * volunteers and an expert working the queue, so the verification rate, the response time
      and the resolution rate are real numbers rather than dashes;
    * a leaderboard of fourteen residents, two community missions, one of them completed.

The river story runs first (this script calls seed_river_demo, which clears earlier samples),
so the demo script still works exactly as written.

What is and is not real is the same as in seed_river_demo.py: photos are drawn by that script
and stamped "ẢNH MẪU DEMO", the vision result on them is simulated, places are points on the
real OpenStreetMap canal lines, reporters are invented, rain comes from Open-Meteo at run time.
Every row is is_demo = true; the pages show it only with ?demo=1.

    python scripts/seed_city_demo.py             # from backend/
    python scripts/seed_city_demo.py --verify    # the river volunteer step too
"""
# ruff: noqa: RUF001 - Vietnamese canal names use the en dash, and the notes are Vietnamese

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_river_demo as river
from app import alerts, community, verification, waterways
from app.auth import EXPERT, VOLUNTEER, Reviewer
from app.db import load_default_database
from app.detector import load_default_detector
from app.fusion import ReportAnswers
from app.main import scored_observation
from app.pipeline import run_pipeline
from app.quality import check_image
from app.repository import insert_observation
from app.storage import save_photo

VN = timedelta(hours=7)
PREFIX = "demo-city-"
VOLUNTEERS = [Reviewer(PREFIX + "vol-1", VOLUNTEER), Reviewer(PREFIX + "vol-2", VOLUNTEER)]
EXPERT_REVIEWER = Reviewer(PREFIX + "expert", EXPERT)

# --- what people answer ---------------------------------------------------------------------
CLEAN = {"water_color": "normal", "odor": "none", "foam": "no", "oil_sheen": "no",
         "floating_trash": "little", "aquatic_life": "yes", "dead_fish": "no",
         "nearby_place": "home", "contact": "passing", "recent_rain": "none"}
LITTER = {**CLEAN, "floating_trash": "lots", "aquatic_life": "no", "water_color": "brown_black"}
BLACK_WATER = {**CLEAN, "water_color": "brown_black", "odor": "sewage", "floating_trash": "lots",
               "aquatic_life": "no", "contact": "children_nearby"}
FOAMY = {**CLEAN, "foam": "yes", "odor": "chemical", "water_color": "milky_white", "aquatic_life": "no"}
DEAD_FISH = {**CLEAN, "dead_fish": "yes", "odor": "rotten", "water_color": "brown_black",
             "aquatic_life": "no", "contact": "children_nearby"}

# (waterway slug, segment index (1-based), fraction along it, answers, reporter, days ago, hour, goal)
ALONG_THE_CANALS = [
    ("doi-te", 1, 0.3, CLEAN, "a", 19, 7, "environment"),
    ("doi-te", 3, 0.5, LITTER, "b", 17, 16, "environment"),
    ("doi-te", 4, 0.4, CLEAN, "c", 12, 8, "biodiversity"),
    ("tau-hu-ben-nghe", 2, 0.4, CLEAN, "d", 18, 9, "environment"),
    ("tau-hu-ben-nghe", 3, 0.6, LITTER, "e", 11, 17, "environment"),
    ("tau-hu-ben-nghe", 4, 0.3, CLEAN, "f", 6, 7, "child_health"),
    ("tham-luong", 1, 0.5, LITTER, "g", 16, 15, "environment"),
    ("tham-luong", 2, 0.4, CLEAN, "h", 9, 8, "flooding"),
    ("tham-luong", 3, 0.6, {**CLEAN, "overflow": "yes", "recent_rain": "flood_or_heavy"}, "i", 4, 18,
     "flooding"),
    ("ben-cat", 1, 0.4, CLEAN, "k", 15, 10, "biodiversity"),
    ("ben-cat", 3, 0.5, LITTER, "l", 8, 16, "environment"),
    ("nuoc-len", 2, 0.5, CLEAN, "m", 14, 9, "environment"),
    ("nuoc-len", 3, 0.4, {**CLEAN, "odor": "sewage"}, "n", 7, 19, "environment"),
    ("lo-gom", 2, 0.6, CLEAN, "a", 13, 8, "biodiversity"),
    ("song-sai-gon", 2, 0.5, CLEAN, "b", 20, 7, "environment"),
    ("song-sai-gon", 5, 0.4, CLEAN, "c", 10, 15, "biodiversity"),
    ("song-sai-gon", 8, 0.6, LITTER, "d", 5, 17, "environment"),
]

# Three clusters, each three reports close in time and space, each ending differently.
CLUSTERS = [
    {"name": "Nước đen ở Kênh Đôi", "slug": "doi-te", "segment": 2, "fraction": 0.45,
     "answers": BLACK_WATER, "reporters": ("e", "f", "g"), "days_ago": 2.0, "hours": (19, 21, 7),
     "goal": "child_health", "photo": {"sheen": False, "trash": 7, "murky": True},
     "ending": "resolved"},
    {"name": "Cá chết ở Tàu Hủ – Bến Nghé", "slug": "tau-hu-ben-nghe", "segment": 1, "fraction": 0.55,
     "answers": DEAD_FISH, "reporters": ("h", "i", "k"), "days_ago": 1.6, "hours": (8, 10, 16),
     "goal": "environment", "photo": {"sheen": False, "trash": 5, "murky": True},
     "ending": "confirmed"},
    {"name": "Bọt trắng ở Lò Gốm", "slug": "lo-gom", "segment": 1, "fraction": 0.5,
     "answers": FOAMY, "reporters": ("l", "m", "n"), "days_ago": 1.2, "hours": (7, 9, 15),
     "goal": "environment", "photo": {"sheen": True, "trash": 2, "murky": False},
     "ending": "open"},
]

# Away from the canals: containers holding water, and one fly cluster. (lat, lon) are residential
# points in District 8, Bình Thạnh and Gò Vấp, rounded the way a phone would give them.
STANDING_WATER = [
    {"name": "Lốp xe sau nhà, Q.8", "latitude": 10.7385, "longitude": 106.6412,
     "answers": {"water_stagnant": "yes", "container_type": "used_tire", "standing_days": "gt_7",
                 "organic_waste": "yes", "nearby_place": "home", "contact": "children_nearby",
                 "recent_rain": "within_48h", "moving_organisms": "unknown"},
     "group": "aedes_breeding_risk", "reporters": ("a", "b", "c"), "days_ago": 9.0,
     "hours": (8, 15, 9), "treated": True},
    {"name": "Chậu cây trường học, Bình Thạnh", "latitude": 10.8039, "longitude": 106.7085,
     "answers": {"water_stagnant": "yes", "container_type": "flower_pot", "standing_days": "d4_7",
                 "organic_waste": "no", "nearby_place": "school", "contact": "children_nearby",
                 "recent_rain": "within_48h", "moving_organisms": "yes"},
     "group": "aedes_breeding_risk", "reporters": ("d", "e"), "days_ago": 5.0,
     "hours": (9, 16), "treated": True},
    {"name": "Cống tắc, Gò Vấp", "latitude": 10.8382, "longitude": 106.6653,
     "answers": {"water_stagnant": "yes", "container_type": "blocked_drain", "standing_days": "gt_7",
                 "organic_waste": "yes", "nearby_place": "home", "contact": "passing",
                 "recent_rain": "flood_or_heavy"},
     "group": "culex_environmental_risk", "reporters": ("f", "g", "h"), "days_ago": 2.2,
     "hours": (7, 11, 18), "treated": False},
    {"name": "Ruồi ở chợ, Q.8", "latitude": 10.7411, "longitude": 106.6289,
     "answers": {"insect_seen": "many_flying_insects", "density": "many", "seen_where": "near_garbage",
                 "organic_waste": "yes", "near_food_place": "yes", "nearby_place": "home",
                 "dead_animal_or_feces": "no"},
     "group": "fly_cluster", "reporters": ("i", "k", "l"), "days_ago": 1.8,
     "hours": (10, 12, 17), "treated": False},
]


def segments_of(slug: str) -> list[dict]:
    path = waterways.DATA_DIR / f"{slug}.geojson"
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def point_on(slug: str, segment: int, fraction: float, offset_m: float) -> tuple[float, float]:
    """A point along a canal segment, `offset_m` to the side, the way a phone fix sits off the line."""
    coords = segments_of(slug)[segment - 1]["geometry"]["coordinates"]
    i = min(int(fraction * (len(coords) - 1)), len(coords) - 2)
    (x1, y1), (x2, y2) = coords[i], coords[i + 1]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    deg = offset_m / 111_320
    return y1 - dx / length * deg, x1 + dy / length * deg


def when(days_ago: float, hour: int, now: datetime) -> datetime:
    local_day = (now + VN).date() - timedelta(days=math.floor(days_ago))
    moment = datetime(local_day.year, local_day.month, local_day.day, hour, 20, tzinfo=UTC) - VN
    return moment - timedelta(days=1) if moment > now else moment


async def send(database, state, *, answers: dict, group: str, reporter: str, latitude: float,
               longitude: float, observed: datetime, photo: dict) -> tuple:
    """One report, scored by the real pipeline and stored the way the API stores it."""
    picture = river.drawn_photo(hash((reporter, observed.isoformat())) % 10_000, **photo)
    quality = check_image(picture)
    state.vision.sheen = photo.get("sheen", False)
    report = ReportAnswers.model_validate({**answers, "observation_group": group})
    container_group = group in ("aedes_breeding_risk", "culex_environmental_risk", "mosquito_activity")
    result = await run_pipeline(state, picture, report, quality, conf_floor=0.05, with_water=False,
                                with_vision=True, with_detector=container_group)
    stored = save_photo(picture)
    item = scored_observation(result, reporter_id=PREFIX + reporter, latitude=latitude,
                              longitude=longitude, location_accuracy_m=12, observed_at=observed,
                              image_path=stored.relative_path, image_sha256=stored.sha256,
                              image_phash_hex=str(quality.metrics["phash"]), is_demo=True)
    with database.connect() as conn:
        observation_id, duplicate_of = insert_observation(conn, item)
        task = (verification.queue(conn, observation_id, result.review)
                if result.review.decision == "verify" else None)
        community.award_report(conn, item.reporter_id, observation_id, duplicate_of is not None)
        alerts.refresh(conn)
    return observation_id, task, result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true",
                        help="also run the river story's volunteer step")
    args = parser.parse_args()

    print("=== 1 · Câu chuyện kênh Nhiêu Lộc – Thị Nghè (seed_river_demo.py) ===")
    sys.argv = ["seed_river_demo.py"] + (["--verify"] if args.verify else [])
    await river.main()          # clears earlier samples, then seeds the story

    database = load_default_database()
    if database is None:
        sys.exit("Database not reachable. Run: docker compose up -d db")
    state = SimpleNamespace(detector=load_default_detector(), water=None, vision=river.SimulatedVision())
    now = datetime.now(UTC)
    rng = random.Random(20260922)

    print("\n=== 2 · Quan sát dọc các tuyến kênh khác ===")
    for slug, segment, fraction, answers, who, days_ago, hour, goal in ALONG_THE_CANALS:
        latitude, longitude = point_on(slug, segment, fraction, offset_m=rng.uniform(8, 20))
        observed = when(days_ago, hour, now)
        _, _, result = await send(database, state, answers={**answers, "observation_goal": goal},
                                  group="river_health", reporter=who, latitude=latitude,
                                  longitude=longitude, observed=observed,
                                  photo={"sheen": False, "trash": rng.randint(0, 6),
                                         "murky": answers is LITTER})
        print(f"  {slug} đoạn {segment} · {observed + VN:%d/%m %H:%M} · "
              f"rủi ro {result.vector_watch.group_score or 0:.2f} · mức {result.assessment.level}")

    print("\n=== 3 · Ba cụm báo cáo mở thành cảnh báo ===")
    cluster_tasks: dict[str, list] = {}
    for cluster in CLUSTERS:
        tasks = []
        for n, (who, hour) in enumerate(zip(cluster["reporters"], cluster["hours"], strict=True)):
            latitude, longitude = point_on(cluster["slug"], cluster["segment"],
                                           cluster["fraction"] + 0.01 * n, offset_m=10 + 4 * n)
            observed = when(cluster["days_ago"] - 0.3 * n, hour, now)
            _, task, result = await send(
                database, state, answers={**cluster["answers"], "observation_goal": cluster["goal"]},
                group="river_health", reporter=who, latitude=latitude, longitude=longitude,
                observed=observed, photo=cluster["photo"])
            if task:
                tasks.append(task)
            print(f"  {cluster['name']} · {observed + VN:%d/%m %H:%M} · "
                  f"mức {result.assessment.level} · {result.review.decision}")
        cluster_tasks[cluster["ending"]] = tasks

    print("\n=== 4 · Nước đọng, ruồi: ngoài kênh ===")
    treat_tasks = []
    for site in STANDING_WATER:
        for n, (who, hour) in enumerate(zip(site["reporters"], site["hours"], strict=True)):
            observed = when(site["days_ago"] - 0.4 * n, hour, now)
            _, task, result = await send(
                database, state, answers=site["answers"], group=site["group"], reporter=who,
                latitude=site["latitude"] + n * 0.00018, longitude=site["longitude"] + n * 0.00015,
                # Each photo of a site must look different, or the duplicate check drops it and
                # the cluster never reaches the three reports a hotspot needs.
                observed=observed, photo={"sheen": n % 2 == 1, "trash": 3 + 6 * n,
                                          "murky": n % 2 == 0})
            if task and site["treated"] and n == 0:
                treat_tasks.append((site, task))
            print(f"  {site['name']} · {observed + VN:%d/%m %H:%M} · "
                  f"điểm nhóm {result.vector_watch.group_score or 0:.2f} · mức {result.assessment.level}")

    print("\n=== 5 · Người xác minh làm việc ===")
    with database.connect() as conn:
        # A volunteer confirms the dead-fish cluster on site: that is what turns it orange.
        for task_id in cluster_tasks.get("confirmed", [])[:2]:
            verification.claim(conn, task_id, VOLUNTEERS[0])
            verification.submit(conn, task_id, VOLUNTEERS[0], "confirmed",
                                "Thấy cá chết dọc bờ, mùi hôi nặng.")
        # The black-water cluster was checked and then cleaned up.
        for task_id in cluster_tasks.get("resolved", [])[:2]:
            verification.claim(conn, task_id, VOLUNTEERS[1])
            verification.submit(conn, task_id, VOLUNTEERS[1], "confirmed",
                                "Nước đen, mùi cống nặng; đơn vị vệ sinh môi trường đã đến.")
        # Oil sheen, dead fish and chemical smells need an expert, so those tasks wait escalated
        # until one signs them off. Signing them off is what turns a report into a verified one.
        for task_id in cluster_tasks.get("resolved", [])[:2] + cluster_tasks.get("confirmed", [])[:1]:
            verification.resolve(conn, task_id, EXPERT_REVIEWER, "confirmed",
                                 "Chuyên gia xác nhận kết luận của tình nguyện viên.")
        changes = alerts.refresh(conn)
        for change in changes:
            print(f"  cảnh báo {change['change']} -> {change['level']}")
        # Close the black-water alert only: it is the one the story says was cleaned up. Picking it
        # by distance keeps the Nhiêu Lộc alert of the demo script untouched.
        latitude, longitude = point_on("doi-te", 2, 0.45, 0)
        nearest = conn.execute(
            """
            SELECT id FROM alerts
            WHERE is_demo AND category = 'water_quality' AND status IN ('open', 'verified')
            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography LIMIT 1
            """, (longitude, latitude)).fetchone()
        if nearest:
            alerts.verify(conn, nearest["id"], EXPERT_REVIEWER, "resolved",
                          "Đã xử lý: nạo vét rác và khơi thông cửa xả.")
            print("  cảnh báo nước đen được chuyên gia đóng lại (đã xử lý)")

    # A mission is created first and the work happens after it: only the after-photos
    # sent once the mission is open count towards completing it.
    print("\n=== 6 · Nhiệm vụ cộng đồng ===")
    with database.connect() as conn:
        done = community.create_task(
            conn, EXPERT_REVIEWER, title="Dọn vật chứa đọng nước quanh chợ Q.8",
            description="Sau mưa, kiểm tra vật chứa quanh khu vực, đổ nước và chụp ảnh sau xử lý.",
            category="vector", latitude=STANDING_WATER[0]["latitude"],
            longitude=STANDING_WATER[0]["longitude"], radius_m=600, target_count=1,
            reward_points=80, deadline=now + timedelta(days=2), alert_id=None)
        conn.execute("UPDATE community_tasks SET is_demo = true WHERE id = %s", (done["id"],))
        open_task = community.create_task(
            conn, EXPERT_REVIEWER, title="Kiểm tra bờ kênh Lò Gốm sau đợt bọt trắng",
            description="Đi dọc đoạn 1, chụp mặt nước và bờ, trả lời màu nước, mùi và bọt.",
            category="water_quality", latitude=point_on("lo-gom", 1, 0.5, 0)[0],
            longitude=point_on("lo-gom", 1, 0.5, 0)[1], radius_m=800, target_count=3,
            reward_points=120, deadline=now + timedelta(days=5), alert_id=None)
        conn.execute("UPDATE community_tasks SET is_demo = true WHERE id = %s", (open_task["id"],))
        print(f"  đã giao: {done['title']}")

    print("\n=== 7 · Ảnh trước và sau xử lý ===")
    with database.connect() as conn:
        for site, task_id in treat_tasks:
            verification.claim(conn, task_id, VOLUNTEERS[0])
            before = save_photo(river.drawn_photo(hash(site["name"]) % 9_000, False, 3, True))
            after = save_photo(river.drawn_photo(hash(site["name"] + "after") % 9_000, False, 0, False))
            verification.add_photo(conn, task_id, VOLUNTEERS[0], "before", before.relative_path,
                                   0.72, {"note": "Ảnh mẫu demo"})
            verification.add_photo(conn, task_id, VOLUNTEERS[0], "after", after.relative_path,
                                   0.18, {"note": "Ảnh mẫu demo, đã đổ nước"})
            verification.submit(conn, task_id, VOLUNTEERS[0], "confirmed",
                                "Đã đổ nước, úp ngược vật chứa.")
            print(f"  {site['name']}: điểm nhóm 0.72 -> 0.18")
        try:
            result = community.complete_task(conn, done["id"], VOLUNTEERS[0])
            print(f"  hoàn thành: {done['title']} (+{result['points']} điểm)")
        except Exception as exc:  # noqa: BLE001 - a mission without enough after-photos stays open
            print(f"  nhiệm vụ vẫn mở: {exc}")
        print(f"  đang mở: {open_task['title']}")

    print("\n=== Tổng kết ===")
    with database.connect() as conn:
        counts = conn.execute(
            """
            SELECT (SELECT count(*) FROM observations WHERE is_demo) AS observations,
                   (SELECT count(*) FROM observations WHERE is_demo AND status = 'verified') AS verified,
                   (SELECT count(*) FROM observations WHERE is_demo AND group_score_after IS NOT NULL) AS treated,
                   (SELECT count(*) FROM alerts WHERE is_demo) AS all_alerts,
                   (SELECT count(*) FROM alerts WHERE is_demo AND status IN ('open', 'verified')) AS open_alerts,
                   (SELECT count(*) FROM community_tasks WHERE is_demo) AS missions,
                   (SELECT count(DISTINCT user_id) FROM points_ledger WHERE user_id LIKE 'demo-%%') AS people
            """).fetchone()
        duplicates = conn.execute(
            "SELECT count(*) AS n FROM observations WHERE is_demo AND duplicate_of IS NOT NULL"
        ).fetchone()["n"]
        print(f"  {counts['observations']} quan sát · {counts['verified']} đã xác minh · "
              f"{counts['treated']} có ảnh sau xử lý · {duplicates} bị coi là ảnh trùng")
        print(f"  {counts['all_alerts']} cảnh báo ({counts['open_alerts']} đang mở) · "
              f"{counts['missions']} nhiệm vụ · {counts['people']} người dân")
        for row in conn.execute(
                """
                SELECT level, status, category, count(*) AS n FROM alerts WHERE is_demo
                GROUP BY 1, 2, 3 ORDER BY n DESC
                """):
            print(f"    {row['category']}: {row['level']} / {row['status']} × {row['n']}")
    print("\nXem: /?demo=1  ·  /dashboard?demo=1  ·  /passport?segment=nhieu-loc-thi-nghe-2&demo=1")


if __name__ == "__main__":
    asyncio.run(main())
