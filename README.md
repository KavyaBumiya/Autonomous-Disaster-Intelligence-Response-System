# AEGIS-AI

> Autonomous Emergency & Geospatial Intelligence System
> Multi-modal disaster intelligence pipeline: voice and text citizen reports,
> social media ingestion, transformer NLP, trust scoring, deterministic priority
> scoring, and a real-time operator console.

---

## Project Structure

```
AEGIS-AI/
|-- backend/                     # FastAPI + Python backend
|   |-- app/
|   |   |-- main.py              # FastAPI app + Socket.IO mount + lifespan
|   |   |-- core/                # Settings, async engine, external API config
|   |   |-- models/              # SQLAlchemy ORM models
|   |   |-- schemas/             # Pydantic request/response schemas
|   |   |-- api/                 # Route handlers (reports, incidents, decision, ...)
|   |   |-- services/            # Whisper STT, NLP, geocoding, dedup, websocket
|   |   |-- agents/              # Orchestrator, verification, detection agents
|   |   |-- ai/                  # Provider registry, router, queue, vision, XAI
|   |   |-- integrations/        # USGS, NASA, weather, maps, routing, traffic
|   |   |-- engine/              # Decision engine + XAI, prediction, commander
|   |   |-- pollers/             # Weather, seismic, EONET, social schedulers
|   |   |-- auth/                # Request-identity dependencies
|   |   `-- utils/
|   |-- alembic/                 # Database migrations
|   |-- tests/                   # Backend tests
|   |-- requirements.txt
|   `-- Dockerfile
|-- frontend/                    # Operator console (React + TypeScript + Vite)
|   |-- src/App.tsx              # App shell: nav, roles, notifications, toast
|   |-- src/lib/consoleData.tsx  # Single data provider for every panel
|   |-- src/lib/api.ts           # Thin, abortable, time-boxed fetch wrapper
|   |-- src/lib/hooks.ts         # Polling resource hooks (never throw in render)
|   |-- src/lib/mappers.ts       # Backend payloads -> view models
|   |-- src/lib/fallbacks.ts     # Honest no-data values (never invented figures)
|   |-- src/pages/               # One module per console screen
|   `-- smoke/build.mjs          # Offline-render honesty test (npm run smoke)
|-- scripts/                     # Utility scripts
|   |-- download.sh              # Downloads fine-tuned NLP model weights
|   `-- make-favicon.ps1
|-- docs/                        # Project documentation & PRDs
|-- docker-compose.yml
|-- .env.example
|-- .gitignore
`-- README.md
```

---

## Quick Start

### Operator console (frontend)

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

`frontend/.env` points at the deployed API, so the console opens onto a live
command dashboard with no local infrastructure required.

> The deployed API runs on a free tier that sleeps when idle, so the first
> request after a pause can take 45-90s to wake it. This surfaces as
> "Connecting" in the feed badge, not as an error.

To run against a local backend instead, clear `VITE_API_BASE_URL` and
`VITE_SOCKET_URL` and set `VITE_USE_DEV_PROXY=true`; Vite then proxies `/api`
and `/socket.io` to `VITE_DEV_PROXY_TARGET`.

### Verification

```bash
cd frontend
npm run verify   # typecheck + offline-render honesty test + production build
```

`npm run smoke` renders every console page with the backend unreachable and
asserts two things: the full UI chrome still renders, and **no fabricated
figure appears**. A command console that reports "3,200 people at risk" after a
failed read is worse than one that reports nothing, because an operator cannot
tell a plausible number from a real one.

### Full stack (backend + infrastructure)

```bash
# 1. Copy and fill in your API keys
cp .env.example .env

# 2. Download NLP model weights (first time only)
bash scripts/download.sh

# 3. Boot Postgres/Redis/backend
docker-compose up --build
```

| Service | URL |
|---------|-----|
| Console | http://localhost:5173 |
| API root | http://localhost:8000/api |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/health |

**Production (Render):**

| Path | URL |
|------|-----|
| API root | `https://autonomous-disaster-intelligence.onrender.com/api` |
| Swagger | `https://autonomous-disaster-intelligence.onrender.com/docs` |
| Health | `https://autonomous-disaster-intelligence.onrender.com/api/health` |

### Backend local development (without Docker)

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
# Schema bootstrap (create_all + column reconcile + alembic stamp) runs on
# startup, so there is no separate seed step.
# socket_app, not app: it mounts the Socket.IO ASGI app alongside the REST API.
uvicorn app.main:socket_app --reload --port 8000
```

---

## Console screens

| Screen | What it does |
| --- | --- |
| **Overview** | KPI tiles, live map, verified incident feed, route and resource summaries |
| **Report Intake** | Submit a text or voice field report and watch the pipeline resolve it into a scored incident |
| **Live Map** | Layered operational map with per-layer visibility toggles |
| **Incidents** | Triage queue with the Decision Engine's XAI rationale and a generated response workflow |
| **Resources** | Capacity tracking, supply pressure, and resource registration |
| **Routes** | Hazard-aware corridors recomputed against a blocked-road list |
| **Teams** | Field team readiness and dispatch instructions (pending approval) |
| **Prediction Engine** | Multi-hazard projections, forecast timeline, and the evidence trail behind each number |
| **Resource Commander** | The human approval gate over AI-proposed allocations |
| **AI Assistant** | Conversational access to the live operational picture |
| **Flood Simulation** | Client-side flood modelling and what-if scenarios |

### Report Intake

`POST /api/reports` is the only request path that runs the entire intelligence
chain: input moderation, NLP parse, geocoding, zone resolution, verification,
detection, deterministic priority scoring, then XAI. The API returns `201` as
soon as the row is stored and everything after that runs as a backend
background task, so Report Intake watches for the resulting incident instead of
assuming an immediate response.

A report **without any location** is stored and audited but never raises an
incident, because the console will not place a hazard it cannot locate. The form
therefore defaults coordinates to the monitored zone centroid.

> **Known backend gap:** the social-media poller writes reports straight to the
> database and never calls the orchestrator, so social-only ingestion produces
> no zones and no incidents. Only the report-ingestion path is wired end to end.
> See `backend/app/pollers/social.py:_process_post`.

---

## Authentication

This deployment runs **unauthenticated**: there is no sign-in, session or token,
and every guarded route accepts anonymous callers. Routes still record
`approved_by` for audit purposes, but that field records a fixed `operator`
label, not a person. Add real authentication before treating it as an audit
trail.

---

## Health Endpoints

| Endpoint | Purpose | Touches dependencies |
| --- | --- | --- |
| `/healthz` | Process liveness -- what the platform should poll | No |
| `/readyz` | Readiness: process up **and** database reachable (503 if not) | Database |
| `/api/health` | Detailed operational status: providers, database, cache | Database + cache |

Use `/healthz` for container liveness so a transient database blip cannot make
the platform restart a healthy process.

---

## The flood model

Flood occurrence is scored by a **fitted** logistic regression trained on 144
real GDACS flood records (2019–2026) with 245 near-miss negatives, using ERA5
rainfall from Open-Meteo. Cross-validated ROC-AUC **0.6406**, against **0.5825**
for the hand-tuned rules baseline and 0.5 for a coin flip.

It is composed with the existing propagation arithmetic rather than replacing
it, and it degrades to those rules if the artifact is missing or malformed.

Because the training set over-samples positives, the score is a **ranking
signal, not a calibrated probability** — rank zones with it, do not display
`0.72` as a 72% chance of flooding. Rebuild with `python -m ml.flood_dataset`
then `python -m ml.train_flood_model` from `backend/`.

Full data provenance, metrics, limitations, and known gaps:
[`docs/flood-model.md`](docs/flood-model.md).
