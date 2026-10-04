import pytest
from psycopg.conninfo import conninfo_to_dict
from scripts.seed_local_demo import local_database


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_demo_uses_separate_local_database(host):
    url = f"host={host} dbname=aquapulse user=aquapulse password=example port=5432"
    info = conninfo_to_dict(local_database(url))
    assert info["host"] == host
    assert info["dbname"] == "aquapulse_demo"
    assert info["user"] == "aquapulse"


@pytest.mark.parametrize("url", [
    "postgresql://user:example@3.148.215.37/aquapulse",
    "host=production.example.com dbname=aquapulse",
    "host=localhost hostaddr=3.148.215.37 dbname=aquapulse",
    "dbname=aquapulse",  # no explicit host: inherited PGHOST might point at production
])
def test_demo_refuses_remote_or_ambiguous_database(url):
    with pytest.raises(ValueError, match="localhost"):
        local_database(url)
