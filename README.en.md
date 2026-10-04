# AquaPulse — a health station for urban rivers

*IEEE OneAquaHealth Global Hackathon 2026. Vietnamese version: [README.md](README.md).*

A resident photographs a canal. Sixty seconds later the city has a signal it can act on — and,
just as importantly, a statement of how certain that signal is.

AquaPulse detects environmental signs, estimates a risk, and asks a person to verify it. It does
**not** diagnose disease, does not claim a mosquito carries a virus, does not decide from a photo
that water is contaminated, and never recommends spraying chemicals by itself. The boundary is
code, not prose: see `GET /scope` and [backend/app/domain.py](backend/app/domain.py).

The interface is bilingual. Vietnamese is the language people report in; **VI | EN** in the top bar
switches every page, and `?lang=en` on any URL opens it in English
(for example `http://127.0.0.1:8010/?lang=en&demo=1`). The scene model is asked in the reader's
language too, so its description of a photo comes back in English on an English page.

## Why this, and why it looks the way it does

Urban canals are watched by the people who live beside them, every day, for free. What is missing
is not observation but *structure*: a way to turn "the water is black again this morning" into
something a city department can act on without either ignoring it or over-reacting to it.

Three design decisions follow from that, and they run through the whole system:

1. **Risk and confidence are separate numbers.** A worrying report from a single night photo is
   high risk and low confidence. The system says both, always, and never averages them into one
   reassuring figure.
2. **A model that did not look is not a model that saw nothing.** When the container detector is
   not run (a photo of a canal surface is not what it was trained on), that source is removed from
   the confidence denominator instead of voting "nothing there".
3. **People decide, the AI prepares.** An unverified river report is capped at yellow. Orange needs
   a volunteer who went to the site. Red needs an expert. The AI's own suspicion never raises a
   level by itself — it turns into a question for the reporter.

## Run it

```bash
docker compose up -d db                 # PostgreSQL 18 + PostGIS 3.6, bound to localhost
cd backend
python -m venv .venv
.venv/Scripts/Activate.ps1              # Windows PowerShell; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8010
```

Migrations in `db/migrations/` run at start-up. Without a database `/detect` still works, while
`/observations` and `/hotspots` answer 503.

| Page | For |
|---|---|
| `/` | Home: observations today, open alerts, the canal map, the risk passports, evidence-carrying alerts, the translator, the OneAquaHealth network, community |
| `/report` | Send an observation in four steps: photo, questions for the chosen group, place and time, send. Step 1 picks the analysis mode: **containers and standing water** (YOLO11n + water model + description AI) or **water surface and other signs** (description AI only) |
| `/tasks-board` | Community missions; volunteers and experts sign in with a token to verify, send before/after photos, close alerts, create missions |
| `/dashboard` | Expert view: metrics, reports per day, before/after treatment, areas to watch, a four-layer map |
| `/passport?segment=…` | One canal stretch: five indices, explanations, history, rain, signs, life, community, alerts, press |

A 3–5 minute demo with real numbers: [docs/demo-script.en.md](docs/demo-script.en.md).

## The river work, in detail

- **The "river and canal" form** (the default at `/report`): the reporter's goal (environment,
  children's health, flooding, biodiversity) and seven things anyone can see or smell — colour,
  odour, foam, oil sheen, floating litter, living fish or shrimp, dead fish.
- **Two analysis modes** (`with_detector` on `POST /detect` and `POST /observations`). Containers
  holding water run YOLO11n and the water segmentation model; a canal surface, floating litter or
  an oil sheen runs neither, because neither was trained on such a scene — the description model
  and the reporter's answers carry it. When a model does not run, the system records "did not
  look", not "looked and saw nothing".
- **Three separate scores** per observation: Risk (pollution signs), Eco (ecological state, 1 =
  looks healthy), Human-health (children, contact with water, odour) — beside the confidence.
- **Yellow until someone checks.** A volunteer's on-site confirmation raises an alert to orange;
  only an expert reaches red. When the vision model sees a sign the reporter did not mention, the
  app asks, with the model's own certainty: *"The photo suggests an oil sheen, 70% confidence. Did
  you see a rainbow film or smell fuel?"*
- **Alerts carry their evidence** in five parts: what happened, where the evidence comes from, how
  confident it is (photos taken at night count 0.8), who should verify, what people should do now.
- **Canal stretches and risk passports.** Eight Ho Chi Minh City waterways, 35 stretches (Nhiêu Lộc
  – Thị Nghè, Tàu Hủ – Bến Nghé, Kênh Đôi – Kênh Tẻ, Tham Lương, Bến Cát, Nước Lên, Lò Gốm, the
  Saigon River). Geometry comes from OpenStreetMap via
  `python backend/scripts/build_waterways.py` into `db/data/*.geojson`, loaded at start-up.
  `GET /waterways`, `GET /waterways/{id}/passport`, page `/passport?segment=…`: Eco, Risk,
  Confidence, Trend, Human-health, rule-written explanations, history, measured rain (Open-Meteo),
  life in the water, participation, alerts. In OSM the Tham Lương – Bến Cát – Nước Lên system is
  three disconnected pieces (the joining sections are unnamed), so it stays three waterways rather
  than one line drawn across dry land.
- **Eco–Human Health Translator** (`GET /translator?question=children|odor|after_rain|biodiversity`):
  answers built by rules, never by a language model, each carrying the data used, the certainty,
  what is not known, and advice that is not medical advice.
- **FHIR R4**: `GET /fhir/Observation/{id}`, `GET /fhir/waterways/{id}` (a Bundle of Location,
  RiskAssessment and Observation; no reporter ids, coordinates rounded).
- **Sample data**: `python backend/scripts/seed_river_demo.py [--verify]`; pages show it only when
  opened with `?demo=1`. The sample photos are drawings stamped "ẢNH MẪU DEMO" (sample photo), and
  the AI part of those samples is simulated.

## Responsible AI, concretely

| The claim a demo would like to make | What the system actually does |
|---|---|
| "The AI detected an oil sheen" | It marks "suspected" and asks the reporter. No oil-sheen detector has been trained. |
| "The water is safe / toxic" | Never stated. Only sampling and a laboratory can say that. |
| "Reports are up 40%" | A one-sided binomial test decides; below 6 reports in two weeks it says "not enough data to state a trend". |
| "Species X lives here" | Residents answer whether they saw living creatures. No species identification. |
| "An outbreak" | The wording guard rejects any notification containing outbreak language before it is stored. |

Other parts of the same boundary: the reporter's own reliability is computed by the server from
their verified reports, never taken from what they claim; nobody can verify their own report; and
out-of-scope sentences from the vision model are dropped and counted.

## Data from the OneAquaHealth project

AquaPulse reads the project's own open API (`https://api.enora-oah.eu/api`, the one behind the
Resilience Map):

| What is read | What it is used for |
|---|---|
| 5 pilot cities, 106 research sites | A map layer and a list on the home page |
| 69 sites created by residents in the **Citizen Science App** | The same layer, labelled with its source |
| Health-risk indicators (pathogens, faecal pollution, antibiotic-resistance genes) | Shown with the sampling date and a written explanation |
| 500 m urban context, nitrate, measured weather | Context for each monitoring site |

**The boundary is explicit:** those are the project's laboratory measurements. They are displayed,
never mixed into the risk, hotspots or alerts computed from citizen observations. A citizen report
is only *linked* to the nearest monitoring site, with the distance stated. Endpoints:
`GET /oneaqua/cities`, `GET /oneaqua/sites[?city=CO&kind=research|citizen]`,
`GET /oneaqua/sites/{code}`, `POST /oneaqua/sync` (expert). The server syncs at start-up and every
`AQUAPULSE_OAH_SYNC_HOURS` hours (default 24, `0` turns it off).

## What the press reported (since 1 January 2026)

A Google News RSS index (`backend/app/press.py`): title, source, date, link; the canal named in the
headline is matched to our waterway and tagged (litter, black water, smell, dead fish, flooding,
rehabilitation works, wastewater). It appears on each waterway's passport page; `GET /press?waterway=…`,
`POST /press/sync` (expert).

**An article is context, not measurement**: it never enters a risk score, a hotspot, an alert or a
dashboard figure. Only the headline, source, date and link are stored, as a news index does. Four
waterways the press writes about often (Xuyên Tâm, Văn Thánh, 19/5, Bà Lớn) have no geometry in
`db/data` yet and are kept under their own names.

## How a report is routed

After scoring, each report is routed (`review` in the result):

1. A case that must be verified (larvae, oil sheen, a dead animal, a chemical smell, orange/red,
   confidence below 0.60, two models disagreeing) → **the verification queue**, whatever the
   confidence.
2. The reporter contradicts the models, data is missing, or confidence ≤ 0.85 → **ask the reporter
   to confirm** (`POST /observations/{id}/confirm`), then score and route again.
3. Otherwise → **show the preliminary result**.

Verifier accounts live in `.env` (`AQUAPULSE_REVIEWERS`, see `.env.example`) and call the API with
`Authorization: Bearer <token>`: `GET /verification/tasks`, `.../claim`, `.../submit` (volunteer:
`confirmed | not_confirmed | unclear`), `.../resolve` (expert, final), `.../events` (who decided
what, and when).

## Alerts, missions, points, notifications

- **Alerts** are hotspots followed over time: after each report and each verdict, a hotspot is
  matched to an unresolved alert of the same category within 300 m — update it, or open a new one.
  `GET /alerts`, `POST /alerts/{id}/verify` (expert: `verified | resolved | dismissed`).
- **Notifications** (`GET /notifications?latitude=..&longitude=..` or `?reporter_id=..`): a new
  alert, a level raised, a resolution, a point near you that needs verification, the verdict on
  your own report. The wording is fixed and calm; outbreak language is blocked before storage. No
  push, Zalo or SMS yet.
- **Points** (a ledger; each action counts once): +10 for a report with a photo and GPS that is not
  a duplicate, at most 5 a day; +20 when a report is verified as correct; +5 for checking someone
  else's report; +15 for an after photo; plus a mission's reward. Five badges, all computed from
  verified reports. `GET /community/profile/{id}`, `GET /community/leaderboard` (ids masked).
- **Community missions**: an expert creates one (`POST /tasks`), anyone can see them (`GET /tasks`);
  completion (`POST /tasks/{id}/complete`) requires after photos for enough points inside the radius.
- **Metrics** `GET /dashboard/metrics?days=14`: reports, verified and the rate, open alerts, response
  time (verification − arrival), hotspot resolution rate, risk drop before/after, reports after
  rain, and a daily series.

## Privacy

- Faces are blurred (YuNet, `backend/models/`) before a photo is stored or sent to an external scene-description service, such as the Kimi API.
  **Licence plates are not blurred yet**: no usable detector for Vietnamese plates has been added.
- Photos are re-encoded, so no EXIF or GPS from the phone survives on disk. Stored photos are
  visible to verifiers only.
- The public map and API round positions to about 100 m and never return `reporter_id`; the
  leaderboard masks ids.
- Residents use an anonymous id generated in the browser (`localStorage`) — no name, no phone
  number.

## Deployment

```bash
docker build -t aquapulse-api .          # from the repository root
docker run -p 8000:8000 -e DATABASE_URL=... -e AQUAPULSE_REVIEWERS=... \
  -v aquapulse-photos:/data/photos aquapulse-api
```

- The repository includes the two serving ONNX models and the YuNet face detector, so a fresh
  clone has the model files needed by the Docker build. Training checkpoints, datasets and
  local photos/videos are excluded. See [model provenance](ml/runs/README.md).
  The image runs as a normal user and contains no `.env`.
- Database: PostgreSQL with PostGIS (Supabase or Render Postgres with the extension enabled).
- Photos live in `/data/photos` and need a durable volume. Supabase Storage is not implemented.
- Environment variables: [.env.example](.env.example) holds names and non-secret examples only.
  **No API key or token belongs in git**; put them in the deployment's secret configuration.

## Models and training

```bash
python ml/prepare_vistext.py           # data/raw/vistext-mosquito -> data/{images,labels}
docker build -t aquapulse-ml ml        # PyTorch CUDA + Ultralytics
docker run -d --name aquapulse-train --gpus all --shm-size=4g \
  -v "$PWD:/workspace" aquapulse-ml bash /workspace/ml/train_all.sh
```

Training runs in Docker because Smart App Control on Windows 11 blocks PyTorch's unsigned DLLs; a
Linux container is unaffected and still uses the GPU. Each evaluation
(`ml/runs/<name>/eval/report.json`) records the confidence threshold chosen on the validation set,
per-class precision and recall, per-image recall, and how well the confidences are calibrated.

Scene description uses `kimi-k3` through Alibaba Model Studio's OpenAI-compatible API.
Copy `.env.example` to `.env`, change the following settings, and enter your own API key on the
machine running the backend:

```dotenv
AQUAPULSE_VISION_ENABLED=1
AQUAPULSE_VISION_PROVIDER=kimi
DASHSCOPE_API_KEY=your-model-studio-api-key
KIMI_MODEL=kimi-k3
KIMI_BASE_URL=https://ws-ojz5frpqw24ibm8d.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
```

Restart the backend after changing `.env`. With a key configured, the app calls scene description
automatically; there is no checkbox to enable it. Photos are face-blurred, resized and re-encoded
before being sent to the external service. Kimi describes visible signs; the backend computes risk
and decides when human verification is needed. Never commit `.env`. Without a key, the backend
does not load the Kimi client. Qwen through Ollama and Gemini adapters remain available in code,
selected through `AQUAPULSE_VISION_PROVIDER`.

## Tests

```bash
backend/.venv/Scripts/python.exe -m pytest backend    # needs docker compose up -d db for the PostGIS tests
python -m pytest ml/tests
python -m ruff check .
```

`backend/tests/test_i18n.py` loads the English version of every reader-facing endpoint and fails if
a Vietnamese sentence is left in it.

Before a demo, walk every feature against the running server:

```bash
cd backend
python -m uvicorn app.main:app --port 8010   # in another shell
python scripts/demo_check.py
```

It follows the demo script beat by beat — home page, evidence alert, passport in both languages,
translator, a volunteer's verification raising the alert to orange, a real photo through the
models, OneAquaHealth, the press index, points, FHIR — prints one PASS/FAIL line per feature, and
deletes the rows it created. Screenshots of each beat: [docs/demo-frames/](docs/demo-frames/).

## Licence and data sources

- The detector is trained with Ultralytics YOLO11, licensed **AGPL-3.0**. Serving it to users
  obliges the team to publish the source or buy an Enterprise licence.
- Training images come from [VisText-Mosquito](https://data.mendeley.com/datasets/rtsfh7jh7p/2)
  (CC BY 4.0). Per-image provenance is in `data/sources.csv`; excluded images and the reason are in
  `data/excluded.csv`.
- Canal geometry: © OpenStreetMap contributors (ODbL). Rain: Open-Meteo. Monitoring data:
  the OneAquaHealth project. Press index: Google News RSS.
