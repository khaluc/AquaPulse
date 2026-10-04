"""Storing observations and finding hotspots, against a real PostGIS database."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app import repository
from PIL import Image

from tests.factories import jpeg_bytes, noise_photo

# Around District 10, Ho Chi Minh City. 0.001 degree of latitude is about 111 m.
LAT, LON = 10.7626, 106.6602
DEG_PER_M = 1 / 111_320


def _post(client, photo=None, **fields):
    form = {"latitude": str(LAT), "longitude": str(LON), **{k: str(v) for k, v in fields.items()}}
    image = jpeg_bytes(photo or noise_photo())
    return client.post("/observations", data=form, files={"image": ("a.jpg", image, "image/jpeg")})


def _count(database):
    with database.connect() as conn:
        return conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"]


# --- POST /observations ---------------------------------------------------------------

def test_observation_is_scored_stored_and_located(client_with_database, database, tmp_path):
    response = _post(client_with_database, location_accuracy_m=12,
                     captured_at="2026-09-17T15:30:00+07:00", reporter_id="alice",
                     answers='{"water_stagnant": "yes", "nearby_place": "home"}')
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] in ("pending", "needs_confirmation", "needs_verification")
    assert "vector" in body["categories"]

    with database.connect() as conn:
        row = conn.execute(
            "SELECT ST_AsText(geom) AS wkt, observed_at, image_path, reporter_id, answers "
            "FROM observations WHERE id = %s", (body["id"],)
        ).fetchone()
    assert row["wkt"] == f"POINT({LON} {LAT})"
    assert row["observed_at"] == datetime(2026, 9, 17, 8, 30, tzinfo=UTC)  # +07:00 kept
    assert row["answers"]["water_stagnant"] == "yes"

    stored = tmp_path / "photos" / row["image_path"]
    with Image.open(stored) as picture:
        assert not picture.getexif()  # no GPS or device data on disk


def test_unusable_photo_is_rejected_before_anything_is_stored(client_with_database, database, tmp_path):
    response = _post(client_with_database, photo=noise_photo(blur=6))
    assert response.status_code == 422
    assert _count(database) == 0
    assert not (tmp_path / "photos").exists()


def test_bad_location_or_time_is_rejected(client_with_database):
    assert client_with_database.post(
        "/observations", data={"latitude": "0", "longitude": "0"},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo()), "image/jpeg")},
    ).status_code == 422
    assert _post(client_with_database, location_accuracy_m=800).status_code == 422
    assert _post(client_with_database, captured_at="2026-09-17T15:30:00").status_code == 422  # no timezone
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    assert _post(client_with_database, captured_at=future).status_code == 422


def test_same_photo_sent_twice_nearby_is_marked_duplicate(client_with_database):
    photo = noise_photo(seed=7)  # scene_photo is too smooth: the quality gate calls it blurry
    first = _post(client_with_database, photo=photo).json()
    second = _post(client_with_database, photo=photo).json()
    assert first["duplicate_of"] is None
    assert second["duplicate_of"] == first["id"]


def test_storing_needs_a_database(client):
    assert _post(client).status_code == 503


# --- hotspots: the four problems of the plan's query ------------------------------------

def _item(reporter, north_m=0.0, east_m=0.0, hours_ago=1.0, categories=("vector",), seed=0):
    return repository.NewObservation(
        reporter_id=reporter,
        latitude=LAT + north_m * DEG_PER_M,
        longitude=LON + east_m * DEG_PER_M,
        location_accuracy_m=10,
        observed_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        observation_types=[],
        answers={},
        image_path=f"x/{reporter}{seed}.jpg",
        image_sha256=f"{reporter}-{seed}-{north_m}-{east_m}",
        image_phash_hex=f"{(seed * 0x9E3779B97F4A7C15) % 2**64:016x}",  # far apart per seed
        signals=["standing_water"],
        categories=list(categories),
        risk=0.6,
        confidence=0.7,
        level="orange",
        needs_verification=True,
        analysis={},
        status="needs_verification",
    )


def _insert(database, *items):
    with database.connect() as conn:
        return [repository.insert_observation(conn, item)[0] for item in items]


def _hotspots(database, **kwargs):
    with database.connect() as conn:
        return repository.hotspots(conn, **kwargs)


def test_three_reporters_close_together_make_one_hotspot(database):
    ids = _insert(database, _item("a", seed=1), _item("b", 150, 0, seed=2), _item("c", 0, 200, seed=3))
    found = _hotspots(database)
    assert len(found) == 1  # one row per place, not one per report
    spot = found[0]
    assert (spot["reports"], spot["reporters"]) == (3, 3)
    assert set(spot["observation_ids"]) == set(ids)
    assert spot["spread_m"] < 250
    assert abs(spot["latitude"] - LAT) < 0.002


def test_one_person_cannot_make_a_hotspot(database):
    _insert(database, *[_item("alice", i * 10, seed=i + 1) for i in range(3)])
    assert _hotspots(database) == []
    assert len(_hotspots(database, min_reporters=1)) == 1  # the plan's rule would have fired


def test_old_reports_do_not_count(database):
    _insert(database, _item("a", seed=1), _item("b", 100, seed=2), _item("c", 200, hours_ago=240, seed=3))
    assert _hotspots(database) == []
    assert len(_hotspots(database, hours=24 * 11, min_reporters=2)) == 1


def test_other_kinds_of_sign_do_not_count(database):
    _insert(database, _item("a", seed=1), _item("b", 100, seed=2),
            _item("c", 200, categories=("environment",), seed=3))
    assert _hotspots(database, category="vector") == []


def test_lone_and_far_apart_reports_are_not_hotspots(database):
    _insert(database, _item("a", seed=1), _item("b", 2000, seed=2), _item("c", 0, 2000, seed=3))
    assert _hotspots(database) == []


def test_duplicate_photos_do_not_inflate_a_hotspot(database):
    first = _item("a", seed=1)
    resent = replace(first, reporter_id="b", observed_at=first.observed_at + timedelta(minutes=5))
    _insert(database, first, resent, _item("c", 100, seed=3))
    assert _hotspots(database) == []  # only two distinct photos


def test_hotspot_endpoint(client_with_database, database):
    _insert(database, _item("a", seed=1), _item("b", 150, seed=2), _item("c", 0, 200, seed=3))
    body = client_with_database.get("/hotspots").json()
    assert body["parameters"]["radius_m"] == 500
    assert len(body["hotspots"]) == 1
    assert body["hotspots"][0]["reports"] == 3
