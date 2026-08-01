# PowerPlay

Find one specific player in a long sports video and cut their highlights into a single reel.

Give it a video file or a YouTube link plus a description of who to look for (jersey number, kit colours), and it returns an MP4 containing just that player's moments.

> **Status: working prototype.** It runs end to end on real match footage, but there are no user accounts, no deployment story, and identity matching is heuristic rather than learned. See [Known limitations](#known-limitations) before relying on it.

---

## How it works

```
video file ──┐
             ├─► FastAPI (main.py) ─► SQLite job queue (jobs.db) ─► worker.py
YouTube URL ─┘                                                          │
                                                                        ▼
                     ┌──────────────────────────────────────────────────────┐
                     │ 1. acquire   yt-dlp section download, or local upload │
                     │ 2. detect    YOLOv8 persons ─► jersey OCR + colour    │
                     │              histograms + appearance/scene banks      │
                     │ 3. track     merge detections into segments           │
                     │ 4. select    action energy, replay suppression,       │
                     │              dedupe, optional GPT-4o-mini scoring     │
                     │ 5. compile   frame-accurate ffmpeg cuts ─► concat     │
                     └──────────────────────────────────────────────────────┘
                                                                        │
                                              Next.js frontend polls ◄──┘
                                              /jobs/{id} until done
```

The API and the worker are **separate processes** that communicate only through the SQLite job store. The API never does heavy work; every analysis runs in `worker.py`.

## Repository layout

```
powerplay/
├── backend/
│   ├── main.py                  FastAPI app: upload, enqueue, job status
│   ├── worker.py                Job runner — polls the queue, runs the pipeline
│   ├── job_store.py             SQLite persistence for jobs
│   ├── processing/
│   │   ├── detect_player.py     YOLOv8 detection + identity matching (the core)
│   │   ├── segment_selector.py  Ranking, replay suppression, dedupe
│   │   ├── track_player.py      Segment refinement (DeepSORT path is opt-in)
│   │   ├── deepsort_track.py    DeepSORT tracking
│   │   ├── highlight_scorer.py  Optional GPT-4o-mini segment scoring
│   │   ├── compile_clips.py     ffmpeg cutting and concatenation
│   │   ├── practice_mode.py     Motion-based clipping for practice footage
│   │   └── ml/                  Frame-pool classifier (trained, not yet wired in)
│   ├── tools/benchmark_pipeline.py   Segment-IoU precision/recall/F1 harness
│   └── tests/                   pytest unit tests
├── frontend/                    Next.js 15 App Router + React 19 + Tailwind
└── docs/                        Product requirements, technical design, test plan
```

## Running it

Requires **Python 3.13**, **Node 18+**, and **ffmpeg** on your PATH (`brew install ffmpeg`).

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt      # or requirements-dev.txt to run tests
```

The first detection run downloads YOLOv8 weights automatically.

Two processes, two terminals — **both are required**; without the worker, jobs queue forever:

```bash
# Terminal 1 — API on http://localhost:8000 (docs at /docs)
uvicorn main:app --reload

# Terminal 2 — job runner
python worker.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

Point it at the API with `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://127.0.0.1:8000`).

### Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Queue an analysis. Accepts either `video` (file) or `youtube_url`, plus `playerData` JSON |
| `POST` | `/process-video` | Same contract as `/jobs` |
| `GET`  | `/jobs/{job_id}` | Poll status: `stage`, `progress`, `message`, and `result` when done |
| `POST` | `/practice-mode` | Motion-based clipping for practice footage (runs synchronously) |
| `GET`  | `/health` | Liveness check |

`playerData` looks like:

```json
{ "jersey_number": "18", "jersey_color": "blue", "helmet_color": "navy" }
```

Colours must be one of the 14 recognised names, a hex value, or `"r,g,b"` — free text like `"sky blue"` is not parsed.

## Configuration

`OPENAI_API_KEY` enables VLM segment scoring; without it the pipeline uses heuristic selection only.

Roughly 80 `PP_*` environment variables tune detection, selection, and compilation. The ones you are most likely to want:

| Variable | Default | Effect |
|---|---|---|
| `PP_MAX_TOTAL_HIGHLIGHT_SEC` | `130` | Total length cap on the output reel |
| `PP_MAX_SEGMENTS_OUT` | `12` | Maximum clips in the reel |
| `PP_COMPILE_STREAM_COPY` | `false` | Skip re-encoding — much faster, but cuts snap to keyframes |
| `PP_COMPILE_CRF` | `20` | Output quality when re-encoding |
| `PP_ENABLE_DEEPSORT` | off | Use DeepSORT tracking instead of detection-only segments |
| `PP_ENABLE_ANALYSIS_LOW_RES_DOWNLOAD` | `true` | Analyse a low-res copy to cut ingest time |

Grep for `PP_` in `backend/` for the full set.

## Benchmarking

`backend/tools/benchmark_pipeline.py` scores pipeline output against a JSONL ground-truth manifest (`backend/reports/sample_manifest.jsonl`), reporting segment-IoU precision, recall, F1, realtime factor, and an identity-drift proxy. See `backend/BENCHMARK_README.md`.

No baseline results are committed yet — establishing one is the prerequisite for tuning anything in `detect_player.py` or `segment_selector.py` with confidence.

## Known limitations

These are real and worth knowing before you build on this:

- **No authentication, rate limiting, or upload size caps.** Run it locally only.
- **Jobs are lost on refresh.** The job id lives in React state, so closing the tab orphans a running analysis — there is no job list UI to recover it.
- **Identity matching is heuristic.** Jersey OCR plus colour histograms with hand-tuned weights, not a learned re-ID embedding. It drifts onto other players in similar kit, and there is no labelled data to fit against yet.
- **Cricket-specific in places.** Pitch-ROI estimation, `batting`/`bowling` actions, and the GPT scoring prompt all assume cricket.
- **`/practice-mode` blocks the API.** It runs its analysis inline in an async handler, which stalls every other request — including job polling — for the duration.
- **Progress is coarse.** It jumps between fixed stage percentages and sits at 40% through the multi-hour detection phase.
- **The ML layer is disconnected.** `processing/ml/` trains a frame-pool classifier that no inference path ever loads.
- **SQLite is not configured for concurrency** (no WAL, no busy timeout) while the frontend polls every 2 seconds.

## License

MIT
