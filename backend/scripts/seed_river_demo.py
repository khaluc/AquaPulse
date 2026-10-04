"""Sample data for the AquaPulse river demo: the Nhiêu Lộc - Thị Nghè canal, before and after rain.

The story from the brief:
    1. two weeks of ordinary observations along the canal (before the rain);
    2. after the rain, three people send photos of oil sheen on the same stretch (segment 2);
    3. the model is only "suspicious" of oil sheen, it concludes nothing;
    4. the reports cluster, and a yellow alert opens with its evidence;
    5. (live, or --verify) a volunteer confirms on site: the alert turns orange and the
       dashboard keeps "avoid direct contact with the water".

What is and is not real, stated plainly:
- photos are drawn by this script (brown water, rainbow streaks) and stamped "ẢNH MẪU DEMO":
  the repo has no licensed photo of oil sheen on a canal;
- the vision model's "suspected oil sheen" on these photos is simulated (provider
  "demo-simulated"): to show the real model, send a real photo during the demo;
- places are points on the real canal line (OpenStreetMap), reporters are invented;
- rain comes from Open-Meteo at run time and is not invented.
Every row is stored with is_demo = true; pages show it only with ?demo=1.

    python scripts/seed_river_demo.py            # from backend/
    python scripts/seed_river_demo.py --verify   # also run step 5
"""

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

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import alerts, community, verification, waterways
from app.auth import VOLUNTEER, Reviewer
from app.db import load_default_database
from app.detector import load_default_detector
from app.fusion import ReportAnswers
from app.main import scored_observation
from app.pipeline import run_pipeline
from app.quality import check_image
from app.repository import insert_observation
from app.storage import save_photo
from app.vision import Signal, VisionAnalysis

SEGMENTS = json.loads((waterways.DATA_DIR / "nhieu-loc-thi-nghe.geojson").read_text(encoding="utf-8"))["features"]
VN = timedelta(hours=7)
PREFIX = "demo-river-"
VOLUNTEER_ID = PREFIX + "volunteer"
VISION_SIGNALS = ("standing_water", "artificial_container", "organic_waste", "oil_sheen", "foam",
                  "mosquito_larvae", "fly_cluster")


class SimulatedVision:
    """Stands in for Qwen on drawn photos: 'oil sheen, medium certainty' when the scene has it."""

    provider, model, sends_photo_off_device = "demo-simulated", "mô phỏng cho dữ liệu mẫu", False

    def __init__(self):
        self.sheen = False

    def analyze(self, image, lang: str = "vi"):
        # The real client answers in the reader's language; the sample data is always Vietnamese,
        # because that is what a resident's report looks like.
        signals = {name: Signal(name == "oil_sheen" and self.sheen, "medium" if self.sheen else "low")
                   for name in VISION_SIGNALS}
        return VisionAnalysis(signals, self.sheen,
                              "Mô phỏng: có vệt ánh cầu vồng trên mặt nước, nghi là váng dầu." if self.sheen
                              else "Mô phỏng: mặt nước không thấy váng.",
                              "Kết quả mô phỏng cho dữ liệu mẫu, không phải model thật.",
                              self.provider, self.model, 0.0)


def point_on(segment: int, fraction: float, offset_m: float) -> tuple[float, float]:
    """A point along segment `segment` (1-4) at `fraction` of its vertices, `offset_m` off the line."""
    coords = SEGMENTS[segment - 1]["geometry"]["coordinates"]
    i = min(int(fraction * (len(coords) - 1)), len(coords) - 2)
    (x1, y1), (x2, y2) = coords[i], coords[i + 1]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    deg = offset_m / 111_320
    return y1 - dx / length * deg, x1 + dy / length * deg  # lat, lon, perpendicular to the line


def drawn_photo(seed: int, sheen: bool, trash: int, murky: bool) -> Image.Image:
    rng = random.Random(seed)
    base = (92, 78, 48) if murky else (58, 88, 80)
    image = Image.new("RGB", (1024, 768), base)
    draw = ImageDraw.Draw(image)
    for y in range(0, 768, 6):  # ripples
        shade = rng.randint(-14, 14)
        draw.line([(0, y), (1024, y + rng.randint(-8, 8))],
                  fill=tuple(max(0, min(255, c + shade)) for c in base), width=3)
    if sheen:
        for k in range(7):
            y0 = rng.randint(120, 600)
            color = [(200, 90, 200), (90, 180, 220), (230, 210, 90), (120, 220, 140)][k % 4]
            draw.arc([rng.randint(-200, 400), y0, rng.randint(600, 1200), y0 + rng.randint(80, 200)],
                     0, 180, fill=color, width=rng.randint(6, 12))
    for _ in range(trash):
        x, y = rng.randint(50, 950), rng.randint(80, 700)
        draw.rectangle([x, y, x + rng.randint(20, 60), y + rng.randint(10, 30)],
                       fill=rng.choice([(230, 230, 230), (40, 120, 200), (220, 60, 60)]))
    image = image.filter(ImageFilter.GaussianBlur(0.6))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle([0, 0, 1024, 64], fill=(249, 255, 0))
    draw.text((20, 8), "ẢNH MẪU DEMO · không phải ảnh thật", fill=(26, 26, 26), font=font)
    return image


CLEAN = {"water_color": "normal", "odor": "none", "foam": "no", "oil_sheen": "no", "floating_trash": "little",
         "aquatic_life": "yes", "dead_fish": "no", "nearby_place": "home", "contact": "passing", "recent_rain": "none"}
OILY = {"water_color": "rainbow_sheen", "odor": "sewage", "foam": "no", "oil_sheen": "yes", "floating_trash": "little",
        "aquatic_life": "no", "dead_fish": "no", "nearby_place": "home", "recent_rain": "flood_or_heavy"}

# (days ago, local hour, segment, fraction along it, answers, reporter, sheen in photo, trash, murky, goal)
BEFORE = [
    (13, 7, 1, 0.3, CLEAN, "a", False, 2, False, "environment"),
    (12, 16, 2, 0.4, CLEAN, "b", False, 1, False, "biodiversity"),
    (11, 9, 3, 0.5, {**CLEAN, "floating_trash": "none"}, "c", False, 0, False, "biodiversity"),
    (10, 17, 4, 0.6, {**CLEAN, "water_color": "brown_black"}, "d", False, 3, True, "environment"),
    (9, 8, 2, 0.6, CLEAN, "e", False, 1, False, "child_health"),
    (8, 10, 3, 0.2, CLEAN, "f", False, 2, False, "environment"),
    (6, 15, 1, 0.7, CLEAN, "a", False, 1, False, "flooding"),
    (5, 9, 4, 0.3, {**CLEAN, "floating_trash": "lots", "water_color": "brown_black"}, "g", False, 8, True, "environment"),
]
AFTER_RAIN = [
    # Three people, the same stretch of segment 2, within a day; two of them at night.
    (0.9, 20, 2, 0.50, {**OILY, "contact": "children_nearby"}, "h", True, 2, True, "child_health"),
    (0.6, 22, 2, 0.53, OILY, "i", True, 1, True, "environment"),
    (0.2, 6, 2, 0.47, {**OILY, "odor": "rotten"}, "k", True, 3, True, "environment"),
    # Elsewhere after the rain: more floating litter, no sheen.
    (0.5, 8, 3, 0.4, {**CLEAN, "floating_trash": "lots", "aquatic_life": "no", "recent_rain": "flood_or_heavy"},
     "l", False, 9, True, "environment"),
]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true", help="also let a volunteer confirm one oil report")
    args = parser.parse_args()
    database = load_default_database()
    if database is None:
        sys.exit("Database not reachable. Run: docker compose up -d db")
    with database.connect() as conn:
        waterways.load_segments(conn)
        # The river story replaces every earlier sample (the older mosquito samples included a
        # "Nhiêu Lộc" cluster that would merge into this one). seed_demo.py can recreate those.
        old = conn.execute("DELETE FROM observations WHERE is_demo").rowcount
        conn.execute("DELETE FROM community_tasks WHERE is_demo")
        conn.execute("DELETE FROM alerts WHERE is_demo")
        conn.execute("DELETE FROM notifications WHERE is_demo")
        conn.execute("DELETE FROM points_ledger WHERE user_id LIKE 'demo-%%'")
    print(f"removed {old} earlier sample reports")

    vision = SimulatedVision()
    state = SimpleNamespace(detector=load_default_detector(), water=None, vision=vision)
    now = datetime.now(UTC)
    today_vn = (now + VN).date()
    oil_tasks = []
    for group, rows in (("Trước mưa", BEFORE), ("Sau mưa", AFTER_RAIN)):
        print(f"\n# {group}")
        for n, (days_ago, hour, segment, fraction, answers, who, sheen, trash, murky, goal) in enumerate(rows):
            local_day = today_vn - timedelta(days=math.floor(days_ago))
            observed = datetime(local_day.year, local_day.month, local_day.day, hour, 10, tzinfo=UTC) - VN
            if observed > now:
                observed -= timedelta(days=1)
            lat, lon = point_on(segment, fraction, offset_m=12 + 5 * (n % 3))
            picture = drawn_photo(hash((group, n)) % 10_000, sheen, trash, murky)
            quality = check_image(picture)
            vision.sheen = sheen
            report = ReportAnswers.model_validate({**answers, "observation_group": "river_health",
                                                   "observation_goal": goal})
            result = await run_pipeline(state, picture, report, quality, conf_floor=0.05, with_water=False,
                                        with_vision=True)
            stored = save_photo(picture)
            item = scored_observation(
                result, reporter_id=PREFIX + who, latitude=lat, longitude=lon, location_accuracy_m=10,
                observed_at=observed, image_path=stored.relative_path, image_sha256=stored.sha256,
                image_phash_hex=str(quality.metrics["phash"]), is_demo=True)
            with database.connect() as conn:
                observation_id, duplicate_of = insert_observation(conn, item)
                task = (verification.queue(conn, observation_id, result.review)
                        if result.review.decision == "verify" else None)
                community.award_report(conn, item.reporter_id, observation_id, duplicate_of is not None)
                changes = alerts.refresh(conn)
            if sheen and task:
                oil_tasks.append(task)
            a = result.assessment
            print(f"  đoạn {segment} {observed + VN:%d/%m %H:%M}  rủi ro {result.vector_watch.group_score or 0:.2f} "
                  f"sinh thái {result.vector_watch.eco_score or 0:.2f}  mức {a.level}  -> {result.review.decision}"
                  + "".join(f"  [cảnh báo {c['change']}: {c['level']}]" for c in changes))

    if args.verify and oil_tasks:
        volunteer = Reviewer(VOLUNTEER_ID, VOLUNTEER)
        with database.connect() as conn:
            verification.claim(conn, oil_tasks[0], volunteer)
            verification.submit(conn, oil_tasks[0], volunteer, "confirmed",
                                "Thấy váng dầu loang khoảng 20 m dọc bờ, mùi cống nặng.")
            print("\n# Tình nguyện viên xác nhận tại hiện trường:",
                  [f"{c['change']} -> {c['level']}" for c in alerts.refresh(conn)] or "không đổi")
    with database.connect() as conn:
        for row in conn.execute("SELECT level, status, evidence FROM alerts WHERE is_demo AND category = 'water_quality'"):
            print(f"\ncảnh báo {row['level']} ({row['status']}): {row['evidence']['what']['reports']} quan sát, "
                  f"độ tin cậy {row['evidence']['confidence_label']}, {row['evidence']['verifier']}")
    print("\nXem: /?demo=1  ·  /passport?segment=nhieu-loc-thi-nghe-2&demo=1")


if __name__ == "__main__":
    asyncio.run(main())
