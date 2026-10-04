"""PostgreSQL + PostGIS access (plan section 5).

Replaces an earlier SQLite module that nothing imported, which also stamped UTC times
with a "+07:00" label. Timestamps now live in TIMESTAMPTZ columns and are compared
by the database, so there is no local-time arithmetic in Python at all.

Migrations are the numbered SQL files in db/migrations, applied once each, in order.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
# Matches docker-compose.yml; override with DATABASE_URL anywhere else.
DEFAULT_URL = "postgresql://aquapulse:aquapulse-dev@127.0.0.1:5432/aquapulse"


class Database:
    def __init__(self, url: str):
        self.url = url

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """One connection per unit of work; commits on success, rolls back on error."""
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=3) as conn:
            yield conn

    def migrate(self) -> list[str]:
        applied = []
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
                applied.append(path.name)
        return applied


def load_default_database() -> Database | None:
    """None when the database is unreachable: scoring still works, storing does not."""
    database = Database(os.environ.get("DATABASE_URL", DEFAULT_URL))
    try:
        database.migrate()
    except psycopg.OperationalError:
        return None
    return database
