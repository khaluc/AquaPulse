"""Start the dedicated local demo: python backend/scripts/run_local_demo.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    profile = ROOT / ".env.local-demo"
    if not profile.exists():
        sys.exit("Run backend/scripts/seed_local_demo.py first.")
    config = {key: value for key, value in dotenv_values(profile).items() if value is not None}
    info = conninfo_to_dict(config.get("DATABASE_URL", ""))
    if (info.get("host") not in ("localhost", "127.0.0.1", "::1")
            or info.get("hostaddr", "127.0.0.1") not in ("127.0.0.1", "::1")
            or info.get("dbname") != "aquapulse_demo"):
        sys.exit("The demo profile must point to the local aquapulse_demo database.")
    os.environ.update(config)
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8008)


if __name__ == "__main__":
    main()
