"""What the press reported about Ho Chi Minh City's canals, from Google News RSS.

Articles are context, not measurement: a headline never enters a risk score, a hotspot or an
alert. Each row keeps only what a news index keeps - title, source, date, link - plus the
canal it names and a few plain tags (rubbish, black water, smell, dead fish, flooding,
rehabilitation works), so a segment's passport can show "what the press said about this
stretch since the start of the year".

Matching is by canal name in the title: several canals in the news (Xuyên Tâm, 19/5,
Văn Thánh, Tân Hóa) have no geometry in db/data yet, and are kept under their own name.
"""
# ruff: noqa: RUF001 - the en dash in canal names is the Vietnamese spelling, not a typo

from __future__ import annotations

import os
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from typing import Any

import httpx
import psycopg

FEED = "https://news.google.com/rss/search"
USER_AGENT = "AquaPulse/0.1 (IEEE OneAquaHealth Hackathon 2026 entry)"
SINCE = date(2026, 1, 1)          # the brief's window: from the start of this year
QUERIES = [
    'kênh rạch ô nhiễm "TP.HCM"',
    'kênh "Nhiêu Lộc" OR "Thị Nghè" ô nhiễm',
    'kênh "Tàu Hủ" OR "Bến Nghé" ô nhiễm',
    '"Kênh Đôi" OR "Kênh Tẻ" ô nhiễm',
    '"Tham Lương" OR "Bến Cát" OR "Nước Lên" kênh ô nhiễm',
    '"Xuyên Tâm" OR "Văn Thánh" OR "Tân Hóa" OR "Lò Gốm" rạch ô nhiễm',
    'kênh TP.HCM "cá chết" OR "nước đen" OR "hôi thối"',
    '"sông Sài Gòn" ô nhiễm nước thải',
]

# Canal names as the press writes them -> the waterway name AquaPulse uses.
WATERWAYS = {
    "nhieu loc": "Kênh Nhiêu Lộc – Thị Nghè", "thi nghe": "Kênh Nhiêu Lộc – Thị Nghè",
    "tau hu": "Kênh Tàu Hủ – Bến Nghé", "ben nghe": "Kênh Tàu Hủ – Bến Nghé",
    "kenh doi": "Kênh Đôi – Kênh Tẻ", "kenh te": "Kênh Đôi – Kênh Tẻ",
    "tham luong": "Kênh Tham Lương", "ben cat": "Rạch Bến Cát", "nuoc len": "Rạch Nước Lên",
    "lo gom": "Kênh Lò Gốm", "tan hoa": "Kênh Lò Gốm",
    "song sai gon": "Sông Sài Gòn",
    # Named in the news, no geometry in db/data yet.
    "xuyen tam": "Rạch Xuyên Tâm", "van thanh": "Rạch Văn Thánh", "19/5": "Kênh 19/5",
    "19-5": "Kênh 19/5", "ba lon": "Rạch Bà Lớn",
}
TAGS = {
    "rác": ("rac", "rác thải", "xà bần"),
    "nước đen": ("nuoc den", "đen ngòm", "đen kịt"),
    "mùi hôi": ("hoi thoi", "boc mui", "mùi hôi"),
    "cá chết": ("ca chet",),
    "ngập": ("ngap", "triều cường"),
    "cải tạo": ("cai tao", "chỉnh trang", "hồi sinh", "dự án", "khởi công"),
    "nước thải": ("nuoc thai", "xả thải", "cống xả"),
}


def fold(text: str) -> str:
    """Vietnamese without diacritics, lower case: matching a title should not depend on tones."""
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").replace("đ", "d")


def waterway_of(title: str) -> str | None:
    folded = fold(title)
    for key, name in WATERWAYS.items():
        if key in folded:
            return name
    return None


def tags_of(title: str) -> list[str]:
    folded = fold(title)
    return [label for label, words in TAGS.items() if any(fold(w) in folded for w in words)]


def parse_feed(xml_text: str, query: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    rows = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = item.findtext("pubDate")
        if not title or not link or not published:
            continue
        try:
            when = datetime.strptime(published, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=UTC)
        except ValueError:
            continue
        source = item.find("{*}source")
        # Google appends " - <source>" to every headline; the source element already has it.
        clean = re.sub(r"\s+-\s+[^-]+$", "", title) if source is not None else title
        rows.append({"url": link, "title": clean, "source": source.text if source is not None else None,
                     "published_at": when, "waterway": waterway_of(title), "tags": tags_of(title),
                     "query": query})
    return rows


def fetch(query: str, http: httpx.Client) -> list[dict[str, Any]]:
    url = FEED + "?" + urllib.parse.urlencode({"q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
    response = http.get(url)
    response.raise_for_status()
    return parse_feed(response.text, query)


def since() -> date:
    raw = os.environ.get("AQUAPULSE_PRESS_SINCE")
    return date.fromisoformat(raw) if raw else SINCE


def sync(database, http: httpx.Client | None = None, queries: list[str] | None = None) -> dict[str, int]:
    own = http is None
    http = http or httpx.Client(timeout=25, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    start = datetime.combine(since(), datetime.min.time(), tzinfo=UTC)
    found, kept, errors = 0, 0, []
    rows: dict[str, dict[str, Any]] = {}
    try:
        for query in queries or QUERIES:
            try:
                items = fetch(query, http)
            except (httpx.HTTPError, ET.ParseError) as exc:
                errors.append(f"{query}: {type(exc).__name__}")
                continue
            found += len(items)
            for row in items:
                if row["published_at"] >= start:
                    rows.setdefault(row["url"], row)
    finally:
        if own:
            http.close()
    with database.connect() as conn:
        for row in rows.values():
            conn.execute(
                """
                INSERT INTO press_mentions (url, title, source, published_at, waterway, tags, query)
                VALUES (%(url)s, %(title)s, %(source)s, %(published_at)s, %(waterway)s, %(tags)s, %(query)s)
                ON CONFLICT (url) DO UPDATE SET title = EXCLUDED.title, waterway = EXCLUDED.waterway,
                    tags = EXCLUDED.tags, fetched_at = now()
                """, row)
            kept += 1
    return {"fetched": found, "since": since().isoformat(), "kept": kept, "errors": len(errors)}


def mentions(conn: psycopg.Connection, waterway: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT url, title, source, published_at, waterway, tags
        FROM press_mentions
        WHERE published_at >= %(start)s AND (%(waterway)s::text IS NULL OR waterway = %(waterway)s)
        ORDER BY published_at DESC
        LIMIT %(limit)s
        """,
        {"start": datetime.combine(since(), datetime.min.time(), tzinfo=UTC), "waterway": waterway,
         "limit": limit}).fetchall()


def summary(conn: psycopg.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT coalesce(waterway, 'Không nêu tên tuyến') AS waterway, count(*) AS articles,
               max(published_at) AS latest
        FROM press_mentions WHERE published_at >= %(start)s
        GROUP BY 1 ORDER BY articles DESC
        """,
        {"start": datetime.combine(since(), datetime.min.time(), tzinfo=UTC)}).fetchall()
    tags = conn.execute(
        """
        SELECT tag, count(*) AS articles FROM press_mentions, unnest(tags) AS tag
        WHERE published_at >= %(start)s GROUP BY tag ORDER BY articles DESC
        """,
        {"start": datetime.combine(since(), datetime.min.time(), tzinfo=UTC)}).fetchall()
    return {"since": since().isoformat(), "by_waterway": rows, "by_tag": tags,
            "note": "Bài báo là thông tin tham khảo, không phải số đo: không dùng để tính điểm rủi ro, "
                    "điểm nóng hay cảnh báo. Nguồn: Google News RSS."}
