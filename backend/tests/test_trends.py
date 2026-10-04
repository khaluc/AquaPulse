from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app import repository
from app.trends import binomial_tail, classify

from tests.test_observations import _hotspots, _insert, _item

VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


# --- the rule itself -----------------------------------------------------------------

def test_plan_example_is_a_possible_not_a_confirmed_increase():
    """Section 15: 4 -> 9 is +125%, but chance alone gives that 13% of the time."""
    trend = classify(current=9, previous=4)
    assert trend.increase == pytest.approx(1.25)
    assert trend.p_value == pytest.approx(1093 / 8192)
    assert trend.trend == "possibly_increasing"


def test_small_counts_are_not_a_trend():
    assert classify(2, 1).trend == "insufficient_data"   # +100% by the plan's rule
    assert classify(2, 0).trend == "insufficient_data"   # +200%


def test_large_clear_rise_is_increasing():
    trend = classify(current=30, previous=10)
    assert trend.trend == "increasing"
    assert trend.p_value < 0.01


def test_small_rise_is_stable_and_clear_drop_is_decreasing():
    assert classify(12, 10).trend == "stable"
    assert classify(3, 20).trend == "decreasing"


def test_binomial_tail():
    assert binomial_tail(0, 5) == 1.0
    assert binomial_tail(5, 5) == pytest.approx(1 / 32)


# --- counting in the database -----------------------------------------------------------

def _daily(database, **kwargs):
    with database.connect() as conn:
        return repository.daily_counts(conn, **kwargs)


def test_daily_counts_cover_two_windows_and_skip_duplicates(database):
    now = datetime.now(UTC)
    first = _item("a", seed=1)
    _insert(database, first,
            _item("b", 150, hours_ago=24 * 3, seed=2),
            _item("c", 0, 200, hours_ago=24 * 10, seed=3),
            _item("d", 3000, hours_ago=24 * 30, seed=4))  # outside both windows
    # the same photo again: a duplicate, must not count
    _insert(database, repository.NewObservation(**{**first.__dict__, "reporter_id": "e",
                                                   "observed_at": now - timedelta(minutes=30)}))
    series = _daily(database, days=7)
    assert len(series) == 14
    assert sum(r["reports"] for r in series[7:]) == 2   # this week: a, b
    assert sum(r["reports"] for r in series[:7]) == 1   # last week: c


def test_days_are_vietnamese_calendar_days(database):
    """06:00 in Hanoi is 23:00 UTC the day before; it belongs to the local day."""
    today_local = datetime.now(VIETNAM).date()
    early_morning = datetime.combine(today_local, datetime.min.time(), VIETNAM) + timedelta(hours=6)
    if early_morning > datetime.now(VIETNAM):
        early_morning -= timedelta(days=1)  # keep it in the past
    item = _item("a", seed=1)
    _insert(database, repository.NewObservation(**{**item.__dict__, "observed_at": early_morning}))
    series = _daily(database, days=1)
    counted_on = [r["day"] for r in series if r["reports"]]
    assert counted_on == [early_morning.date()]


def test_area_filter_limits_counts_to_one_place(database):
    _insert(database, _item("a", seed=1), _item("b", 5000, seed=2))
    everywhere = _daily(database, days=7)
    near = _daily(database, days=7, latitude=_item("x").latitude, longitude=_item("x").longitude, radius_m=1000)
    assert sum(r["reports"] for r in everywhere) == 2
    assert sum(r["reports"] for r in near) == 1


def test_trends_endpoint(client_with_database, database):
    _insert(database, *[_item(f"r{i}", i * 30, hours_ago=2 + i, seed=i + 1) for i in range(8)])
    body = client_with_database.get("/trends?days=7").json()
    assert (body["current"], body["previous"]) == (8, 0)
    assert body["trend"] == "increasing"
    assert len(body["series"]) == 14
    assert client_with_database.get("/trends?latitude=10.7").status_code == 422


def test_hotspots_report_unclustered_noise(client_with_database, database):
    _insert(database, _item("a", seed=1), _item("b", 150, seed=2), _item("c", 0, 200, seed=3),
            _item("lone", 5000, seed=4))
    body = client_with_database.get("/hotspots").json()
    assert len(body["hotspots"]) == 1
    assert (body["reports_considered"], body["unclustered"]) == (4, 1)
    assert len(_hotspots(database)) == 1
