# AEGIS-AI

> Autonomous Emergency & Geospatial Intelligence System  
> Multi-modal disaster intelligence pipeline: voice reports, social media ingestion, transformer NLP, trust scoring, real-time WebSocket dashboard.

---

## Project Structure

```
AEGIS-AI/
â”œâ”€â”€ backend/                     # FastAPI + Python backend
â”‚   â”œâ”€â”€ app/
â”‚   â”‚   â”œâ”€â”€ main.py              # FastAPI app + Socket.IO mount
â”‚   â”‚   â”œâ”€â”€ core/                # Core configuration & database
â”‚   â”‚   â”‚   â”œâ”€â”€ config.py        # Settings (pydantic-settings)
â”‚   â”‚   â”‚   â”œâ”€â”€ database.py      # Async SQLAlchemy engine + session
â”‚   â”‚   â”‚   â””â”€â”€ apis_config.py   # External API configurations
â”‚   â”‚   â”œâ”€â”€ models/              # SQLAlchemy ORM models
â”‚   â”‚   â”œâ”€â”€ schemas/             # Pydantic request/response schemas
â”‚   â”‚   â”œâ”€â”€ api/                 # Route handlers (reports, incidents, zones, authâ€¦)
â”‚   â”‚   â”œâ”€â”€ services/            # Whisper STT, NLP, geocoding, deduplication, WebSocket
â”‚   â”‚   â”œâ”€â”€ agents/              # Detection, verification, orchestrator agents
â”‚   â”‚   â”œâ”€â”€ engine/              # Decision engine + XAI, prediction engine, resource commander
â”‚   â”‚   â”œâ”€â”€ pollers/             # Weather, seismic, social media pollers
â”‚   â”‚   â”œâ”€â”€ auth/                # JWT tokens + role-based dependencies
â”‚   â”‚   â””â”€â”€ utils/               # Utility functions
â”‚   â”œâ”€â”€ alembic/                 # Database migrations
â”‚   â”œâ”€â”€ tests/                   # Backend tests
â”‚   â”œâ”€â”€ requirements.txt
â”‚   â””â”€â”€ Dockerfile
â”œâ”€â”€ scripts/                     # Utility scripts
â”‚   â””â”€â”€ download.sh              # Downloads fine-tuned NLP model weights
â”œâ”€â”€ docs/                        # Project documentation & PRDs
â”‚   â””â”€â”€ architecture/            # Architecture documentation
â”œâ”€â”€ docker-compose.yml
â”œâ”€â”€ .env.example
â”œâ”€â”€ .gitignore
â””â”€â”€ README.md
```

---

## Quick Start

```bash
# 1. Copy and fill in your API keys
cp .env.example .env

# 2. Download NLP model weights (first time only)
bash scripts/download.sh

# 3. Boot the full stack
docker-compose up --build
```

| Service   | URL                        |
|-----------|---------------------------|
| API root  | http://localhost:8000/api  |
| API docs  | http://localhost:8000/docs |
| Health    | http://localhost:8000/api/health |

> The operator UI is built and hosted separately from this repository. Point
> it at the API above and set `FRONTEND_ORIGIN` in `.env` to allow its origin.

### API surface

| Path | Purpose |
|------|---------|
| `/api` | JSON API metadata (name, version, docs, health links) |
| `/docs` | Swagger UI |
| `/openapi.json` | OpenAPI specification |
| `/api/health` | Health check `{"status":"ok","version":"1.0.0"}` |

**Production (Render):**

| Path | URL |
|------|-----|
| API root | `https://autonomous-disaster-intelligence.onrender.com/api` |
| Swagger | `https://autonomous-disaster-intelligence.onrender.com/docs` |
| Health | `https://autonomous-disaster-intelligence.onrender.com/api/health` |

---

## Demo Login Credentials

| Role      | Email                    | Password |
|-----------|--------------------------|----------|
| Commander | commander@aegis.demo     | demo123  |
| Responder | responder@aegis.demo     | demo123  |
| Analyst   | analyst@aegis.demo       | demo123  |

---

## Local Development (without Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
# Schema bootstrap (create_all + column reconcile + alembic stamp) runs on
# startup, so there is no separate seed step.
# socket_app, not app: it mounts the Socket.IO ASGI app alongside the REST API.
uvicorn app.main:socket_app --reload --port 8000
```

> No frontend step: the operator UI lives outside this repository.

---

## Health Endpoints

| Endpoint | Purpose | Touches dependencies |
| --- | --- | --- |
| `/healthz` | Process liveness â€” what the platform should poll | No |
| `/readyz` | Readiness: process up **and** database reachable (503 if not) | Database |
| `/api/health` | Detailed operational status: providers, database, cache | Database + cache |

Use `/healthz` for container liveness so a transient database blip cannot make
the platform restart a healthy process.
