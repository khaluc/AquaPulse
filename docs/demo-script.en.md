# Demo script, 3–5 minutes: the Nhiêu Lộc – Thị Nghè canal

*Vietnamese version: [demo-script.md](demo-script.md).*

The story from the AquaPulse brief: before the rain → after the rain → three people report an oil
sheen on the same stretch → the AI only says "suspected" → a yellow alert that carries its evidence
→ a volunteer verifies on site → the alert updates and tells people to avoid contact with the water.

The numbers below are what the system produced after `seed_river_demo.py` ran (18 September 2026).
Rainfall comes from Open-Meteo for real, so it changes with the day you run it.

## Before you start

```bash
docker compose up -d db
cd backend
python scripts/seed_river_demo.py        # PowerShell: set $env:PYTHONIOENCODING="utf-8" first
python -m uvicorn app.main:app --port 8010
```

- **Port:** on this machine Docker Desktop holds port 8000, so the examples use 8010. Any port
  works; change it in the links below.
- You need a `.env` with `AQUAPULSE_REVIEWERS` containing one `volunteer` and one `expert` account
  (see `.env.example`). The tokens live there and are never committed. Without that line, step 4
  cannot sign in.
- Run the seed script shortly before the demo so the "after the rain" part falls inside the last
  24 hours.
- Open in advance: `/?lang=en&demo=1`, `/passport?segment=nhieu-loc-thi-nghe-2&lang=en`,
  `/tasks-board?lang=en`, `/report?lang=en`. `?demo=1` once turns sample data on for the whole
  browser session; a yellow banner says so on every page. `?lang=en` (or **EN** in the top bar)
  switches the interface, including the sentences the server writes.
- **Say this to the judges:** the photos in the sample data are drawings stamped "ẢNH MẪU DEMO"
  (sample photo), and the AI's "suspected oil sheen" on those images is simulated. To see the real
  models, send a real photo in step 5.

## The script

**0:00 · The problem (20 seconds).** "People see the canal every day: the colour, the smell, the
litter, the sheen. Those observations stay scattered, hard to read, and nothing acts on them.
AquaPulse is a health station for urban rivers."

**0:20 · Home (40 seconds).** Nhiêu Lộc – Thị Nghè is split into four stretches, coloured by level;
stretch 2 is yellow. The "Canal risk passports" register gives each stretch its Eco, Risk,
Confidence, Trend and Human-health figures. Under "Alerts":

> Yellow · 3 observations within 500 m reported oil sheen (3), unusual odour (3), floating litter (3)
> over 22 hours.
> Evidence: 3 different people, 3 photos; the AI only marked them "suspected", concluding nothing.
> Confidence: medium (0.74) · most photos taken at night.
> Who verifies: a volunteer team needs to verify this on site.
> What to do now: avoid direct contact with the water until test results are in.

Say: "Those are the five parts of an alert that carries its evidence. No 'dirty water', no
'outbreak'."

**1:00 · The passport of stretch 2 (50 seconds).** Eco 0.31 · Risk 0.67 · Confidence medium ·
Human-health 0.77. The explanation is written from the numbers by rules: *"Confidence is medium,
because most observations were sent at night, when colour and sheen are hard to see, and nobody
has verified on site"*, *"Add 2 daytime observations before issuing a formal alert"*, *"Keep children
from playing or wading in this stretch until verification comes back"*. The charts show 14 days of
observations and the measured rain. Press "Should children play near here?": the answer states the
data it used, how certain it is, what is not known, and advice that is not medical advice.

**1:50 · Verification (50 seconds).** `/tasks-board`, sign in as the volunteer. Claim one oil-sheen
report on stretch 2, choose "Yes, as reported", note "sheen spread about 20 m along the bank". Back
on the home page the alert has **risen to orange**, its evidence now says "1 report confirmed on
site", the next verifier becomes "an environmental expert needs to take samples", and the advice to
avoid contact stays. Red is an expert's decision only.

**2:40 · Send a real observation (60 seconds).** `/report`. Step 1 picks the analysis mode: "Water
surface, other signs" (description AI only) for a canal photo, or "Containers, standing water" if
you photograph a basin or a tyre — only then do YOLO11n and the water model run. The river form is
already selected. Take or choose a real photo and switch on "Ask the AI to describe the scene"
(Qwen runs on this machine; the photo never leaves the server). Pick a goal and answer five to
seven questions: colour, odour, foam, oil sheen, floating litter, living fish. If the AI sees a
sign you did not mention, it asks back: *"The photo suggests an oil sheen, 70% confidence. Did you
see a rainbow film or smell fuel?"* The result keeps Risk, Eco, Confidence and Human-health
relevance apart. After sending, the page says which stretch the observation belongs to and offers
"Join the verification" and "Flag something wrong".

**3:20 · The project's own data (20 seconds).** Scroll to "The European monitoring network":
AquaPulse reads OneAquaHealth's open API. Choose Benevento: 20 research sites with the project's
health-risk index, plus 69 sites created by residents in the Citizen Science App. Click one:
pathogens, faecal pollution, antibiotic-resistance genes, the sampling date, nitrate, measured
weather. Say it plainly: **their numbers are displayed, never mixed into our risk scores**; a
citizen report is only linked to the nearest monitoring site, with the distance.

**3:40 · Interoperability (20 seconds).** Open
`/fhir/waterways/nhieu-loc-thi-nghe-2?include_demo=true`: a FHIR Bundle with Location (the stretch),
RiskAssessment (the passport) and Observation (each report, without reporter ids).

**4:00 · Close (20 seconds).** "AquaPulse turns a resident's photo into a signal you can act on, and
always says how certain that signal is."

## Do not say

| Easy to say | What is true |
|---|---|
| "The AI detected an oil sheen" | It marks "suspected" and asks back. No oil-sheen detector has been trained; in the sample data that part is simulated. |
| "The canal water is safe / toxic" | The system cannot conclude that. Only sampling and a laboratory can. |
| "Reports are up 40%" | On the sample data the system says "not enough data to state a trend" — three unusual reports is too few. It deliberately refuses to inflate. |
| "Species X lives on this stretch" | Residents only answer whether they saw living fish, shrimp or insects. No species identification. |

## If something breaks

- No network: the base map and the rain chart stay empty; everything else works.
- No "Ask the AI to describe the scene" checkbox in step 1: the server found no model. Usually the
  Ollama installed natively on Windows holds port 11434 (and has no models) while the model lives in the
  `aquapulse-ollama` container. Check with `curl http://127.0.0.1:11434/api/tags`: if it answers
  `{"models":[]}`, quit Ollama on Windows (including `ollama app`), run `docker restart aquapulse-ollama`,
  then restart the backend.
- Qwen not running: skip the "Ask the AI" step; nothing else depends on it.
- To start over (the alert back at yellow): `python scripts/seed_river_demo.py`. To have the
  verification step already done: add `--verify`.
