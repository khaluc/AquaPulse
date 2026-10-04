"""The press index: headlines about the canals, kept as context and never as a measurement."""
# ruff: noqa: RUF001 - the en dash in canal names is the Vietnamese spelling, not a typo

import httpx
import pytest
from app import press

FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Rác, nước đen lại bủa vây kênh Nhiêu Lộc - Thị Nghè - VOV</title>
 <link>https://news.google.com/a</link><pubDate>Mon, 24 Aug 2026 03:00:00 GMT</pubDate>
 <source url="https://vov.vn">VOV</source></item>
<item><title>Khởi công cải tạo rạch Xuyên Tâm - Tuổi Trẻ</title>
 <link>https://news.google.com/b</link><pubDate>Thu, 18 Sep 2026 01:00:00 GMT</pubDate>
 <source url="https://tuoitre.vn">Tuổi Trẻ</source></item>
<item><title>Cá chết trắng kênh sau mưa - Dân trí</title>
 <link>https://news.google.com/old</link><pubDate>Wed, 08 May 2024 10:00:00 GMT</pubDate>
 <source url="https://dantri.com.vn">Dân trí</source></item>
</channel></rss>"""


def fake_feed(fail=False):
    def handler(request):
        return httpx.Response(503) if fail else httpx.Response(200, text=FEED)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_titles_are_matched_to_a_canal_and_tagged():
    rows = press.parse_feed(FEED, "test")
    first = rows[0]
    assert first["title"] == "Rác, nước đen lại bủa vây kênh Nhiêu Lộc - Thị Nghè"   # source suffix removed
    assert first["source"] == "VOV" and first["waterway"] == "Kênh Nhiêu Lộc – Thị Nghè"
    assert set(first["tags"]) == {"rác", "nước đen"}
    assert rows[1]["waterway"] == "Rạch Xuyên Tâm" and "cải tạo" in rows[1]["tags"]


def test_sync_keeps_only_this_year_and_is_idempotent(database):
    counts = press.sync(database, fake_feed(), ["q1"])
    assert counts == {"fetched": 3, "since": "2026-01-01", "kept": 2, "errors": 0}   # the 2024 item is out
    press.sync(database, fake_feed(), ["q1"])
    with database.connect() as conn:
        rows = press.mentions(conn)
        overview = press.summary(conn)
    assert len(rows) == 2 and rows[0]["title"].startswith("Khởi công")               # newest first
    assert {r["waterway"]: r["articles"] for r in overview["by_waterway"]} == {
        "Kênh Nhiêu Lộc – Thị Nghè": 1, "Rạch Xuyên Tâm": 1}
    assert "không phải số đo" in overview["note"]


def test_a_failing_feed_is_counted_not_raised(database):
    assert press.sync(database, fake_feed(fail=True), ["q1"]) == {
        "fetched": 0, "since": "2026-01-01", "kept": 0, "errors": 1}


def test_endpoint_filters_by_waterway(client_with_database, database):
    press.sync(database, fake_feed(), ["q1"])
    body = client_with_database.get("/press", params={"waterway": "Rạch Xuyên Tâm"}).json()
    assert [m["title"] for m in body["mentions"]] == ["Khởi công cải tạo rạch Xuyên Tâm"]
    assert body["since"] == "2026-01-01"


def test_press_never_touches_scores(client_with_database, database):
    """An article is not evidence: it must not create a report, a hotspot or an alert."""
    press.sync(database, fake_feed(), ["q1"])
    assert client_with_database.get("/map/points").json()["features"] == []
    assert client_with_database.get("/alerts").json()["alerts"] == []
    assert client_with_database.get("/dashboard/metrics").json()["total_observations"] == 0


def test_sync_is_for_experts(client_with_database, monkeypatch):
    monkeypatch.setenv("AQUAPULSE_REVIEWERS", "volunteer:vol-01:vol-token-123,expert:exp-01:exp-token-789")
    assert client_with_database.post("/press/sync",
                                     headers={"Authorization": "Bearer vol-token-123"}).status_code == 403


@pytest.mark.parametrize("title,expected", [
    ("Kênh Tẻ ngập nặng sau triều cường", ("Kênh Đôi – Kênh Tẻ", "ngập")),
    ("Nước thải xả thẳng ra sông Sài Gòn", ("Sông Sài Gòn", "nước thải")),
    ("Hội thảo về môi trường đô thị", (None, None)),
])
def test_matching_examples(title, expected):
    waterway, tag = expected
    assert press.waterway_of(title) == waterway
    assert (tag in press.tags_of(title)) if tag else press.tags_of(title) == []
