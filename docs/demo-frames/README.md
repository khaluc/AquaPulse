# Demo frames

Screenshots of the running app, one per beat of [demo-script.md](../demo-script.md)
(English: [demo-script.en.md](../demo-script.en.md)). Use them for the submission, for slides, or
as a storyboard while recording the screen.

Captured from a real server on sample data (`seed_river_demo.py`), Chrome at 1440 px wide unless
the name says otherwise. Anything on a canal is real OpenStreetMap geometry; the rain is real
Open-Meteo measurement; the photos in the sample reports are drawings stamped "ẢNH MẪU DEMO".

| File | Beat of the script | Shows |
|---|---|---|
| `01-home-vi.jpg` / `02-home-en.jpg` | 0:20 Home | Hero, canal map, the three counters |
| `03-passport-vi.jpg` / `04-passport-en.jpg` | 1:00 Risk passport | Five indices, the rule-written explanation, 14 days of observations, measured rain, the evidence alert |
| `05-tasks-vi.jpg` | 1:50 Verification | Community missions and the verifier sign-in |
| `06-report-vi.jpg` / `07-report-en.jpg` | 2:40 Send an observation | The four steps, the two analysis modes, the result panel |
| `08-dashboard-vi.jpg` / `09-dashboard-en.jpg` | Expert view | Metrics, reports per day, areas to watch, the four-layer map |
| `10-home-mobile-vi.jpg` | — | The same home page at 520 px |
| `11-home-after-verification-vi.jpg` / `-en.jpg` | 1:50, after the volunteer confirms | The alert at **orange**, "1 at orange or red" in the counters |
| `12-result-tyre-vi.jpg` / `13-result-tyre-en.jpg` | 2:40, dumped tyres holding water | Container mode: YOLO outlines three tyres (1.00, 0.98, 0.81) and the water model paints the water standing in the leaning one. V = 0.90, group score 0.71, level **yellow**, risk 0.49, confidence 0.83. Each tyre carries the badge "unverified: the test set holds only 3 real photos of a tyre", and 12 weaker predictions stay hidden below the display threshold |
| `14-result-litter-vi.jpg` / `15-result-litter-en.jpg` | 2:40, a polluted canal, nothing answered | The scene model sees an oil sheen at **high** certainty and calls the place heavily polluted — and the score stays **green 0.00**, because a model's suspicion never enters the score by itself. It routes to verification and asks the reporter two questions instead |
| `16-result-litter-answered-vi.jpg` / `17-result-litter-answered-en.jpg` | 2:40, the same canal, 9 answers given | With the resident's answers the risk becomes 0.51 at confidence 0.93 (E 0.90, P 0.60, H 0.80) and the level is **held at yellow** until someone verifies on site — the pair 14/15 and 16/17 is the clearest way to show what the AI may and may not decide |

`photo-canal-litter.jpg` is the photo used in frames 14–17: a real canal with floating rubbish and
a dark film on the water, not a picture from the training set. The tyres in frames 12–13 come from
the VisText-Mosquito training split.

To retake them, seed the story, start the server, and run the capture yourself:

```bash
cd backend
python scripts/seed_river_demo.py
python -m uvicorn app.main:app --port 8010
python scripts/demo_check.py      # in another shell: walks every feature and says what worked
```

`demo_check.py` ends with the alert at orange, because it runs the volunteer step. Re-seed before
the demo itself if you want to tell the story from the beginning.
