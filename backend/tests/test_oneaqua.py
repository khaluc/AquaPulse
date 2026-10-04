"""Reading the OneAquaHealth consortium's open API: their sites, their measured indicators,
and the line between their numbers and ours."""

import httpx
import pytest
from app import oneaqua

CITIES = [{"id": "CO", "name": "Coimbra", "latitude": 40.2033, "longitude": -8.4103}]
SITES = [{"code": "C1", "name": "Exploratório", "city": {"id": "CO"}, "latitude": 40.19787,
          "longitude": -8.42865, "altitude": 20.0}]
CITIZEN_SITES = [{"userSiteCode": "UGSX1WpWx", "name": "Agia", "latitude": 35.475978, "longitude": 23.933392,
                  "altitude": None}]
RISKS = [{"researchSiteCode": "C1", "samplingDate": "2023-06-28T00:00:00", "scaledPathogenRisk": 0.2054,
          "scaledFecalRisk": 0.2427, "scaledArgRisk": 0.4792, "healthRiskScore": 0.7266}]
URBAN = [{"researchSiteCode": "C1", "urbanPct500m": 61.2, "imperviousPct500m": 20.91, "vegCoverFrac500m": 29.0,
          "distanceToSewageStations": 3583.11, "distanceToMotorwayRoad": 1350.56}]
ROUTES = {
    "/cities/all": CITIES, "/sites/all": SITES, "/sites/user-generated": CITIZEN_SITES,
    "/resilience-map/health-risks": RISKS, "/resilience-map/urban-parameters": URBAN,
    "/resilience-map/weather": [{"date": "2026-09-20", "precipTotalMm": 4.2, "t2mMeanC": 19.3}],
    "/resilience-map/health-indicators/nitrates/C1": {"siteCode": "C1", "series": [{"date": "2023-06-28",
                                                                                    "statusOfNitrate": 0.004}]},
}


def fake_api(fail: set[str] = frozenset()):
    def handler(request):
        path = request.url.path.removeprefix("/api")
        if path in fail:
            return httpx.Response(503)
        return httpx.Response(200, json=ROUTES[path])

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test/api")


@pytest.fixture
def synced(database):
    oneaqua.sync(database, fake_api())
    oneaqua._cache.clear()
    return database


def test_sync_stores_their_sites_indicators_and_citizen_app_sites(database):
    counts = oneaqua.sync(database, fake_api())
    assert counts == {"cities": 1, "sites": 1, "citizen_sites": 1, "health_risk_rows": 1, "urban_rows": 1}
    with database.connect() as conn:
        rows = oneaqua.sites(conn)
        by_kind = {r["kind"]: r for r in rows}
    assert by_kind["research"]["code"] == "C1" and by_kind["research"]["city_name"] == "Coimbra"
    assert by_kind["research"]["health_risk"] == pytest.approx(0.7266)
    assert by_kind["citizen"]["code"] == "UGSX1WpWx"      # came from their Citizen Science App
    oneaqua.sync(database, fake_api())                     # running twice changes nothing
    with database.connect() as conn:
        assert len(oneaqua.sites(conn)) == 2


def test_their_numbers_are_explained_with_source_and_date(synced):
    with synced.connect() as conn:
        row = oneaqua.site(conn, "C1")
    said = " ".join(oneaqua.explain(row))
    assert "OneAquaHealth đo chỉ số rủi ro sức khỏe 0.73" in said and "28/06/2023" in said
    assert "không phải kết quả của AquaPulse" in said
    assert "21% bề mặt bê tông hóa, 29% cây xanh" in said and "3.6 km" in said
    assert oneaqua.risk_word(0.73) == "cao" and oneaqua.risk_word(0.4) == "trung bình"
    assert oneaqua.risk_word(None) == "chưa có"


def test_sites_endpoint_is_geojson_with_attribution(client_with_database, synced):
    body = client_with_database.get("/oneaqua/sites").json()
    assert len(body["features"]) == 2
    assert "OneAquaHealth" in body["attribution"] and "không trộn vào điểm rủi ro" in body["note"]
    research = client_with_database.get("/oneaqua/sites", params={"kind": "research"}).json()["features"]
    assert [f["properties"]["code"] for f in research] == ["C1"]
    assert research[0]["properties"]["health_risk_word"] == "cao"
    cities = client_with_database.get("/oneaqua/cities").json()["cities"]
    assert cities[0]["name"] == "Coimbra" and cities[0]["research_sites"] == 1


def test_site_detail_adds_their_weather_and_nitrates(client_with_database, synced, monkeypatch):
    monkeypatch.setattr(oneaqua, "client", lambda existing=None: fake_api())
    body = client_with_database.get("/oneaqua/sites/C1").json()
    assert body["site"]["name"] == "Exploratório"
    assert body["history"][0]["health_risk"] == pytest.approx(0.7266)
    assert body["weather"][0] == {"day": "2026-09-20", "mm": 4.2, "temp_c": 19.3}
    assert body["nitrates"][0]["statusOfNitrate"] == 0.004
    assert client_with_database.get("/oneaqua/sites/nope").status_code == 404


def test_weather_failure_is_soft(monkeypatch):
    oneaqua._cache.clear()
    monkeypatch.setattr(oneaqua, "client", lambda existing=None: fake_api(fail={"/resilience-map/weather"}))
    assert oneaqua.weather("C1") is None


def test_a_report_is_linked_to_their_nearest_site_not_merged_into_it(client_with_database, synced):
    import json

    from tests.factories import jpeg_bytes, noise_photo
    near = client_with_database.post(
        "/observations",
        data={"latitude": "40.1980", "longitude": "-8.4288", "reporter_id": "r1",
              "answers": json.dumps({"observation_group": "river_health", "water_color": "normal"})},
        files={"image": ("a.jpg", jpeg_bytes(noise_photo(seed=1)), "image/jpeg")}).json()
    assert near["oneaquahealth_site"]["code"] == "C1"
    assert near["oneaquahealth_site"]["distance_m"] < 200

    far = client_with_database.post(
        "/observations",
        data={"latitude": "10.7860", "longitude": "106.6900", "reporter_id": "r2",
              "answers": json.dumps({"observation_group": "river_health", "water_color": "normal"})},
        files={"image": ("b.jpg", jpeg_bytes(noise_photo(seed=2)), "image/jpeg")}).json()
    assert far["oneaquahealth_site"] is None       # their pilot cities are in Europe
    # Their health-risk score (0.73 at C1) changes nothing in ours: same answers, same score,
    # whether or not one of their sites happens to be next door.
    assert near["assessment"]["risk"] == far["assessment"]["risk"]
    assert near["vector_watch"]["group_score"] == far["vector_watch"]["group_score"]


def test_manual_sync_is_for_experts(client_with_database, monkeypatch):
    monkeypatch.setenv("AQUAPULSE_REVIEWERS", "volunteer:vol-01:vol-token-123,expert:exp-01:exp-token-789")
    assert client_with_database.post("/oneaqua/sync",
                                     headers={"Authorization": "Bearer vol-token-123"}).status_code == 403
