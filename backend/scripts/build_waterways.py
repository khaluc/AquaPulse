"""Build the canal/river segment files in db/data from OpenStreetMap.

Each system below is one named waterway of Ho Chi Minh City, often mapped in OSM as several
ways under different names (Nhiêu Lộc and Thị Nghè are one canal). The script chains those
ways end to end, then cuts the chain into equal segments, which is what a passport is about.

Segment ids stay stable as long as a system's `slug` and its number of segments do not
change, so stored reports keep pointing at the same stretch.

    python scripts/build_waterways.py            # from backend/, queries Overpass
    python scripts/build_waterways.py --cache overpass.json

Geometry: © OpenStreetMap contributors, ODbL.
"""
# ruff: noqa: RUF001 - the en dash in canal names is the Vietnamese spelling, not a typo

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from itertools import pairwise
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "db" / "data"
BBOX = (10.65, 106.55, 10.92, 106.85)  # urban Ho Chi Minh City
MIRRORS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter")
JOIN_TOLERANCE_M = 600  # ways of one canal often stop short of each other at a junction

# (slug, display name, OSM names in order along the water, number of segments)
SYSTEMS = [
    ("nhieu-loc-thi-nghe", "Kênh Nhiêu Lộc – Thị Nghè", ["Kênh Nhiêu Lộc", "Kênh Thị Nghè"], 4),
    ("tau-hu-ben-nghe", "Kênh Tàu Hủ – Bến Nghé", ["Kênh Bến Nghé", "Kênh Tàu Hủ"], 4),
    ("doi-te", "Kênh Đôi – Kênh Tẻ", ["Kênh Tẻ", "Kênh Đôi"], 5),
    # In OSM the Tham Lương - Bến Cát - Nước Lên scheme is three named pieces, kilometres
    # apart because the stretches between them carry no name: keep them as three waterways
    # rather than drawing a line across dry land.
    ("tham-luong", "Kênh Tham Lương", ["Kênh Tham Lương"], 3),
    ("ben-cat", "Rạch Bến Cát", ["Rạch Bến Cát"], 4),
    ("nuoc-len", "Rạch Nước Lên", ["Rạch Nước Lên"], 3),
    ("lo-gom", "Kênh Lò Gốm", ["Kênh Lò Gốm", "Rạch Lò Gốm"], 2),
    ("song-sai-gon", "Sông Sài Gòn", ["Sông Sài Gòn"], 10),
]
NAME_FILTER = "|".join(sorted({n for _, _, names, _ in SYSTEMS for n in names}))


def fetch() -> dict:
    query = (f'[out:json][timeout:120];way["waterway"]["name"~"{NAME_FILTER}"]'
             f'({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});out geom tags;')
    for url in MIRRORS:
        try:
            request = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "AquaPulse/0.1 (hackathon)", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=150) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001 - any mirror may be busy; try the next
            print(f"  {url}: {type(exc).__name__} {exc}"[:110])
    sys.exit("Overpass không phản hồi; thử lại sau hoặc dùng --cache.")


def metres(a, b) -> float:
    radius = 6_371_000
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    d_lat, d_lon = lat2 - lat1, math.radians(b[0] - a[0])
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def chain(pieces: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Assemble ways into continuous lines: start from the longest piece, then keep attaching
    the piece whose nearest end is within JOIN_TOLERANCE_M, flipping it when needed. Pieces
    that never come close enough are a separate line (a branch, or a gap in OSM)."""
    pool = sorted(pieces, key=lambda p: -sum(metres(a, b) for a, b in pairwise(p)))
    lines = []
    while pool:
        line = pool.pop(0)
        joined = True
        while joined and pool:
            joined = False
            best = None
            for index, piece in enumerate(pool):
                for gap, head, ordered in (
                    (metres(line[-1], piece[0]), False, piece),
                    (metres(line[-1], piece[-1]), False, piece[::-1]),
                    (metres(line[0], piece[-1]), True, piece),
                    (metres(line[0], piece[0]), True, piece[::-1]),
                ):
                    if best is None or gap < best[0]:
                        best = (gap, index, head, ordered)
            gap, index, head, ordered = best
            if gap <= JOIN_TOLERANCE_M:
                if gap > 50:
                    print(f"    nối qua khoảng hở {gap:.0f} m")
                pool.pop(index)
                line = ordered[:-1] + line if head else line + ordered[1:]
                joined = True
        lines.append(line)
    return lines


def cut(line: list[tuple[float, float]], parts: int) -> list[tuple[list, float, float]]:
    cumulative = [0.0]
    for a, b in pairwise(line):
        cumulative.append(cumulative[-1] + metres(a, b))
    total = cumulative[-1]

    def at(target: float):
        for i in range(1, len(cumulative)):
            if cumulative[i] >= target:
                span = cumulative[i] - cumulative[i - 1] or 1.0
                f = (target - cumulative[i - 1]) / span
                (x1, y1), (x2, y2) = line[i - 1], line[i]
                return (x1 + f * (x2 - x1), y1 + f * (y2 - y1)), i
        return line[-1], len(line) - 1

    out = []
    for k in range(parts):
        start, end = total * k / parts, total * (k + 1) / parts
        first, i = at(start)
        last, j = at(end)
        out.append(([first, *line[i:j], last], start, end))
    return out


def build(elements: list[dict]) -> int:
    by_name: dict[str, list[dict]] = {}
    for element in elements:
        by_name.setdefault(element["tags"]["name"], []).append(element)
    written = 0
    for slug, title, names, parts in SYSTEMS:
        pieces = []
        for name in names:
            ways = by_name.get(name, [])
            if not ways:
                print(f"  bỏ qua {title}: OSM không có '{name}' trong khung nhìn")
                break
            pieces += [[(p["lon"], p["lat"]) for p in w["geometry"]] for w in
                       sorted(ways, key=lambda w: -len(w["geometry"]))]
        else:
            lines = chain(pieces)
            line = lines[0]
            dropped = sum(len(other) for other in lines[1:])
            if dropped:
                print(f"  {title}: bỏ {len(lines) - 1} khúc rời ({dropped} điểm) không nối được vào tuyến chính")
            features = []
            for k, (coords, start, end) in enumerate(cut(line, parts), start=1):
                features.append({
                    "type": "Feature",
                    "properties": {"id": f"{slug}-{k}", "waterway": title,
                                   "name": f"Đoạn {k} · km {start / 1000:.1f}–{end / 1000:.1f}".replace(".", ","),
                                   "order": k, "from_m": round(start), "to_m": round(end)},
                    "geometry": {"type": "LineString",
                                 "coordinates": [[round(x, 6), round(y, 6)] for x, y in coords]},
                })
            path = DATA_DIR / f"{slug}.geojson"
            path.write_text(json.dumps({
                "type": "FeatureCollection",
                "attribution": (f"Đường {title} từ OpenStreetMap (© OpenStreetMap contributors, ODbL), "
                                f"ghép từ các way có tên {', '.join(names)}; chia {parts} đoạn dài bằng nhau."),
                "features": features}, ensure_ascii=False, indent=1), encoding="utf-8")
            length = sum(metres(a, b) for a, b in pairwise(line))
            print(f"  {title}: {length / 1000:.1f} km, {parts} đoạn -> {path.name}")
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, help="dùng lại kết quả Overpass đã tải")
    args = parser.parse_args()
    data = json.loads(args.cache.read_text(encoding="utf-8")) if args.cache else fetch()
    print(f"{len(data['elements'])} way từ OpenStreetMap")
    print(f"đã ghi {build(data['elements'])} tuyến vào {DATA_DIR}")


if __name__ == "__main__":
    main()
