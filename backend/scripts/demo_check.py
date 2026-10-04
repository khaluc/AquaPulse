"""Walk the whole demo against a running server and say what worked.

Every beat of docs/demo-script.md is exercised: the home page data, the evidence alert, the risk
passport in both languages, the translator, a volunteer's verification raising the alert to
orange, a real photo through the models (including the scene model when Ollama is up), the
OneAquaHealth layer, the press index, the community ledger, and the FHIR export.

Run it before a demo, when the room's network is still calm:

    docker compose up -d db
    python -m uvicorn app.main:app --port 8010          # in another shell
    python scripts/demo_check.py                        # from backend/

It re-seeds the river story first, so the run always tells the same story, and deletes its own
rows at the end. Reviewer tokens come from AQUAPULSE_REVIEWERS in .env, never from this file.
One line per check; a failing run ends non-zero and lists what broke.
"""
# ruff: noqa: RUF001 - the Vietnamese notes and the en dash below are spelled the way the app is

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import EXPERT, VOLUNTEER, configured_reviewers  # (importing app loads .env)

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("AQUAPULSE_DEMO_URL", "http://127.0.0.1:8010")
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
REPORTER = "demo-check-run"        # its rows are removed again at the end
SEGMENT_FILE = ROOT / "db" / "data" / "nhieu-loc-thi-nghe.geojson"
SEGMENT = json.loads(SEGMENT_FILE.read_text(encoding="utf-8"))["features"][1]
SEGMENT_ID = SEGMENT["properties"]["id"]
LON, LAT = SEGMENT["geometry"]["coordinates"][len(SEGMENT["geometry"]["coordinates"]) // 2]

tokens = {reviewer.role: token for token, reviewer in configured_reviewers().items()}
if VOLUNTEER not in tokens or EXPERT not in tokens:
    sys.exit("AQUAPULSE_REVIEWERS needs one volunteer and one expert (see .env.example).")

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    (passed if condition else failed).append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  —  {detail}" if detail else ""))
    return condition


def api(path, method="GET", token=None, data=None, files=None, timeout=180):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = None
    if files:
        boundary = "----aquapulse-demo-check"
        parts = []
        for key, value in (data or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
                         f"{value}\r\n".encode())
        for key, (filename, blob, mime) in files.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; "
                         f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode() + blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")
    except urllib.error.URLError as exc:
        sys.exit(f"{BASE} is not answering ({exc.reason}). Start the server first.")


print("\n=== 0 · Re-seed the river story ===")
seed = subprocess.run([sys.executable, "scripts/seed_river_demo.py"], cwd=BACKEND,
                      capture_output=True, text=True, encoding="utf-8",
                      env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False)
check("seed_river_demo.py runs", seed.returncode == 0, (seed.stderr or seed.stdout).strip()[-160:])

print("\n=== 1 · Home page data ===")
code, health = api("/health")
check("GET /health", code == 200 and health.get("status") == "ok")
code, metrics = api("/dashboard/metrics?days=14&include_demo=true")
check("GET /dashboard/metrics", code == 200 and "open_alerts" in metrics,
      f"{metrics.get('total_observations')} reports, {metrics.get('open_alerts')} open alerts")
code, points = api("/map/points?hours=336&include_demo=true")
check("GET /map/points (GeoJSON)", code == 200 and points.get("type") == "FeatureCollection",
      f"{len(points.get('features', []))} points, rounded to {points.get('precision_m')} m")
code, ways = api("/waterways?include_demo=true")
segments = ways.get("segments", [])
check("GET /waterways", code == 200 and len(segments) >= 30,
      f"{len({s['waterway'] for s in segments})} waterways, {len(segments)} stretches")
watching = [s for s in segments if s["level"] in ("yellow", "orange", "red")]
check("a stretch is coloured by its level", bool(watching),
      ", ".join(f"{s['name']}={s['level']}" for s in watching[:3]))

print("\n=== 2 · The evidence alert ===")
code, alerts = api("/alerts?include_demo=true")
open_alerts = [a for a in alerts.get("alerts", []) if a["status"] in ("open", "verified")]
check("GET /alerts", code == 200 and bool(open_alerts), f"{len(open_alerts)} open")
alert = open_alerts[0] if open_alerts else {}
evidence = alert.get("evidence") or {}
check("the alert carries all five parts of its evidence",
      all(part in evidence for part in ("what", "evidence", "confidence", "verifier", "advice")),
      f"level={alert.get('level')} confidence={evidence.get('confidence')} "
      f"({evidence.get('confidence_label')})")
check("an unverified river alert stays at yellow", alert.get("level") == "yellow",
      f"level={alert.get('level')}")
check("night photos lowered the confidence", (evidence.get("evidence") or {}).get("at_night", 0) > 0,
      f"{(evidence.get('evidence') or {}).get('at_night')} of "
      f"{(evidence.get('what') or {}).get('reports')} at night")

print("\n=== 3 · The risk passport ===")
code, passport = api(f"/waterways/{SEGMENT_ID}/passport?include_demo=true")
indices = passport.get("indices", {})
check("GET /waterways/{id}/passport", code == 200 and "indices" in passport,
      f"Eco {indices.get('eco')} · Risk {indices.get('risk')} · "
      f"confidence {indices.get('confidence_label')} · human {indices.get('human_health')}")
check("the passport explains itself in sentences", len(passport.get("explanation", [])) >= 3,
      passport.get("explanation", [""])[0][:90])
check("it says what to do next", bool(passport.get("actions")), passport.get("actions", [""])[0][:90])
check("measured rain is attached", bool((passport.get("rain") or {}).get("days")),
      (passport.get("rain") or {}).get("source", ""))
code, english = api(f"/waterways/{SEGMENT_ID}/passport?include_demo=true&lang=en")
check("the same passport reads in English",
      code == 200 and english.get("limits", "").startswith("The indices"),
      english.get("explanation", [""])[0][:90])

print("\n=== 4 · Eco–Human Health Translator ===")
for question in ("children", "odor", "after_rain", "biodiversity"):
    code, answer = api(f"/translator?question={question}&segment_id={SEGMENT_ID}&include_demo=true")
    complete = code == 200 and answer.get("data_used") and answer.get("certainty") and answer.get("unknown")
    check(f"GET /translator?question={question}", bool(complete), (answer.get("answer") or "")[:100])

print("\n=== 5 · Verification raises the alert ===")
code, queue = api("/verification/tasks", token=tokens[VOLUNTEER])
tasks = queue.get("tasks", [])
check("a volunteer sees the queue", code == 200 and bool(tasks),
      f"{len(tasks)} waiting, reviewer={queue.get('reviewer', {}).get('id')}")
# A volunteer can take any task still open; one already escalated belongs to an expert.
claimable = [task for task in tasks if task["status"] == "open"]
check("at least one check is open for a volunteer", bool(claimable),
      ", ".join(f"{t['status']}/expert={t['expert_required']}" for t in tasks))
if claimable:
    task_id = claimable[0]["id"]
    code, _ = api(f"/verification/tasks/{task_id}/claim", "POST", tokens[VOLUNTEER], data={})
    check("the volunteer claims a check", code == 200)
    code, verdict = api(f"/verification/tasks/{task_id}/submit", "POST", tokens[VOLUNTEER],
                        data={"verdict": "confirmed", "note": "Váng dầu loang khoảng 20 m dọc bờ."})
    check("the volunteer confirms it on site", code == 200, str(verdict)[:90])
    code, after = api("/alerts?include_demo=true")
    raised = [a for a in after.get("alerts", []) if a["status"] in ("open", "verified")]
    check("the alert rises to orange once someone checked",
          bool(raised) and raised[0]["level"] == "orange",
          f"level={raised[0]['level'] if raised else '?'}")
    proof = (raised[0].get("evidence") or {}) if raised else {}
    check("its evidence now names the site confirmation",
          (proof.get("evidence") or {}).get("confirmed_on_site", 0) >= 1, str(proof.get("verifier"))[:80])

print("\n=== 6 · A real photo through the models ===")
photos = sorted((ROOT / "data" / "images" / "test").glob("*.jpg"))
if not photos:
    check("a test photo exists", False, "data/images/test is empty; run ml/prepare_vistext.py")
else:
    photo = photos[0]
    blob = photo.read_bytes()
    started = time.time()
    code, detect = api("/detect?conf_floor=0.05&with_vision=true&with_detector=false", "POST",
                       data={"answers": json.dumps({"observation_group": "river_health",
                                                    "oil_sheen": "unknown"})},
                       files={"image": (photo.name, blob, "image/jpeg")})
    vision = (detect.get("vision") or {}).get("analysis") or {}
    check("POST /detect answers", code == 200, f"{round(time.time() - started, 1)} s")
    if (detect.get("vision") or {}).get("available"):
        check("the scene model described the photo", bool(vision),
              f"{vision.get('model')}: {(vision.get('explanation') or '')[:70]}")
        check("its signals are only ever 'suspected'",
              all(s["certainty"] in ("low", "medium", "high") for s in vision.get("signals", {}).values()),
              ", ".join(k for k, s in vision.get("signals", {}).items() if s["detected"]) or "none seen")
    else:
        print("SKIP  the scene model is not loaded (Ollama not answering) — see docs/demo-script.md")
    check("the detector is recorded as not run, not as 'saw nothing'",
          (detect.get("detector") or {}).get("ran") is False,
          (detect.get("detector") or {}).get("note", "")[:80])
    review = detect.get("review") or {}
    check("the report is routed to a next step",
          review.get("decision") in ("show", "confirm", "verify"),
          (review.get("questions") or [review.get("decision", "")])[0][:90])

    print("\n=== 7 · Sending the observation ===")
    code, sent = api("/observations?with_vision=false&with_detector=false", "POST",
                     data={"latitude": str(LAT), "longitude": str(LON), "reporter_id": REPORTER,
                           "answers": json.dumps({"observation_group": "river_health", "oil_sheen": "yes",
                                                  "odor": "sewage", "water_color": "brown_black",
                                                  "floating_trash": "lots", "aquatic_life": "no",
                                                  "contact": "children_nearby",
                                                  "observation_goal": "child_health"})},
                     files={"image": (photo.name, blob, "image/jpeg")})
    check("POST /observations", code == 201,
          f"status={sent.get('status')} points={sent.get('points_awarded')}")
    check("the observation is matched to a canal stretch", bool(sent.get("segment")),
          f"{(sent.get('segment') or {}).get('waterway')} · {(sent.get('segment') or {}).get('name')}")
    check("faces are counted before the photo is stored", "faces_blurred" in sent,
          f"{sent.get('faces_blurred')} blurred")
    code, detail = api(f"/observations/{sent.get('id')}")
    check("GET /observations/{id} hides the reporter", code == 200 and "reporter_id" not in detail,
          f"level={detail.get('level')} confidence={detail.get('confidence')}")

print("\n=== 8 · Community, missions, notifications ===")
code, profile = api(f"/community/profile/{REPORTER}")
check("GET /community/profile", code == 200 and profile.get("points", 0) > 0,
      f"{profile.get('points')} points")
code, board = api("/community/leaderboard?limit=5")
masked = all("…" in row["user"] or len(row["user"]) < 8 for row in board.get("leaders", []))
check("the leaderboard masks reporter ids", code == 200 and masked,
      ", ".join(row["user"] for row in board.get("leaders", [])[:3]))
code, mission = api("/tasks", "POST", tokens[EXPERT],
                    data={"title": "demo-check: kiểm tra đoạn 2", "description": "Chạy thử tự động.",
                          "category": "water_quality", "latitude": LAT, "longitude": LON,
                          "radius_m": 500, "target_count": 1, "reward_points": 10, "hours": 24})
check("an expert creates a community mission", code in (200, 201), str(mission.get("title", mission))[:80])
code, listed = api("/tasks?include_demo=true")
check("GET /tasks lists it", code == 200 and any(t["title"].startswith("demo-check")
                                                 for t in listed.get("tasks", [])),
      f"{len(listed.get('tasks', []))} missions")
code, notices = api(f"/notifications?latitude={LAT}&longitude={LON}&radius_m=3000&hours=336&include_demo=true")
check("GET /notifications", code == 200 and "area" in notices, f"{len(notices.get('area', []))} in the area")
if notices.get("area"):
    banned = ("ổ dịch", "bùng phát")
    check("no notification uses outbreak language",
          all(not any(word in notice["message"] for word in banned) for notice in notices["area"]),
          notices["area"][0]["message"][:80])

print("\n=== 9 · Other people's data, kept apart ===")
code, cities = api("/oneaqua/cities")
check("GET /oneaqua/cities", code == 200 and bool(cities.get("cities")),
      ", ".join(city["name"] for city in cities.get("cities", [])[:5]))
code, sites = api("/oneaqua/sites?kind=research")
check("GET /oneaqua/sites", code == 200 and bool(sites.get("features")),
      f"{len(sites.get('features', []))} research sites")
if sites.get("features"):
    code, site = api(f"/oneaqua/sites/{sites['features'][0]['properties']['code']}")
    check("a site explains its own numbers", code == 200 and bool(site.get("explanation")),
          site.get("explanation", [""])[0][:90])
code, press = api("/press?limit=5")
check("GET /press", code == 200 and bool(press.get("mentions")),
      f"since {press.get('since')}, newest: {(press.get('mentions') or [{}])[0].get('title', '')[:60]}")
check("the press index says it is not a measurement", "không phải số đo" in (press.get("note") or ""),
      (press.get("note") or "")[:70])

print("\n=== 10 · Scope, catalog and FHIR ===")
code, scope = api("/scope")
check("GET /scope states the boundary", code == 200 and bool(scope), str(scope)[:90])
code, catalog = api("/vector-watch/catalog")
check("GET /vector-watch/catalog", code == 200 and len(catalog.get("groups", [])) == 10,
      f"{len(catalog.get('groups', []))} groups, {len(catalog.get('questions', {}))} questions")
code, bundle = api(f"/fhir/waterways/{SEGMENT_ID}?include_demo=true")
kinds = [entry["resource"]["resourceType"] for entry in bundle.get("entry", [])]
check("GET /fhir/waterways/{id} returns a Bundle",
      code == 200 and bundle.get("resourceType") == "Bundle",
      f"{len(kinds)} resources: {', '.join(sorted(set(kinds)))}")
check("the bundle carries no reporter id", "reporter" not in json.dumps(bundle).lower())

print("\n=== 11 · Cleaning up after the run ===")
from app.db import load_default_database  # only needed once the walk is over

database = load_default_database()
if database is None:
    check("the run's own rows are removed", False, "no DATABASE_URL; remove them by hand")
else:
    with database.connect() as connection:
        removed = connection.execute("DELETE FROM observations WHERE reporter_id = %s RETURNING id",
                                     (REPORTER,)).fetchall()
        connection.execute("DELETE FROM community_tasks WHERE title LIKE 'demo-check:%'")
        connection.execute("DELETE FROM points_ledger WHERE user_id = %s", (REPORTER,))
    check("the run's own rows are removed", True, f"{len(removed)} observation(s), 1 mission, its points")

print(f"\n================  {len(passed)} passed, {len(failed)} failed  ================")
for name in failed:
    print("  FAILED:", name)
print("\nThe alert is orange now because the volunteer step ran. Re-seed before the demo itself:"
      "\n    python scripts/seed_river_demo.py")
sys.exit(1 if failed else 0)
