import os

# Tests never call the OneAquaHealth API: set before the app (and .env) loads.
os.environ["AQUAPULSE_OAH_SYNC_HOURS"] = "0"
os.environ["AQUAPULSE_PRESS_SYNC_HOURS"] = "0"

import psycopg
import pytest
from app import waterways
from app.db import Database
from app.main import app
from fastapi.testclient import TestClient

from tests.fakes import FakeDetector, FakeSegmenter


@pytest.fixture
def client():
    """App with a fake detector and no water or vision model, whatever this machine has."""
    app.state.detector = FakeDetector()
    app.state.water = None
    app.state.vision = None
    app.state.database = None
    with TestClient(app) as test_client:
        yield test_client
    del app.state.detector, app.state.water, app.state.vision, app.state.database


@pytest.fixture
def client_with_water():
    app.state.detector = FakeDetector()
    app.state.water = FakeSegmenter()
    app.state.vision = None
    app.state.database = None
    with TestClient(app) as test_client:
        yield test_client
    del app.state.detector, app.state.water, app.state.vision, app.state.database


TEST_DATABASE_URL = os.environ.get(
    "AQUAPULSE_TEST_DATABASE_URL", "postgresql://aquapulse:aquapulse-dev@127.0.0.1:5432/aquapulse_test"
)


@pytest.fixture
def database():
    """A real PostGIS database, emptied before each test. Skipped when none is running."""
    db = Database(TEST_DATABASE_URL)
    try:
        db.migrate()
    except psycopg.OperationalError:
        pytest.skip("PostGIS test database not reachable (docker compose up -d db)")
    with db.connect() as conn:
        conn.execute("TRUNCATE observations, alerts, community_tasks, points_ledger, notifications CASCADE")
        conn.execute("TRUNCATE oah_cities, oah_sites, oah_health_risks, oah_urban_context CASCADE")
        conn.execute("TRUNCATE press_mentions")
        waterways.load_segments(conn)
    return db


@pytest.fixture
def client_with_database(database, tmp_path, monkeypatch):
    monkeypatch.setenv("AQUAPULSE_PHOTO_DIR", str(tmp_path / "photos"))
    app.state.detector = FakeDetector()
    app.state.water = FakeSegmenter()
    app.state.vision = None
    app.state.database = database
    with TestClient(app) as test_client:
        yield test_client
    del app.state.detector, app.state.water, app.state.vision, app.state.database
