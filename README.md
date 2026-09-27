# AEGIS-AI

> Autonomous Emergency & Geospatial Intelligence System  
> Multi-modal disaster intelligence pipeline: voice reports, social media ingestion, transformer NLP, trust scoring, real-time WebSocket dashboard.

---

## Project Structure

```
AEGIS-AI/
├── backend/                     # FastAPI + Python backend
│   ├── app/
│   │   ├── main.py              # FastAPI app + Socket.IO mount
│   │   ├── core/                # Core configuration & database
│   │   │   ├── config.py        # Settings (pydantic-settings)
│   │   │   ├── database.py      # Async SQLAlchemy engine + session
│   │   │   └── apis_config.py   # External API configurations
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── api/                 # Route handlers (reports, incidents, zones, auth…)
│   │   ├── services/            # Whisper STT, NLP, geocoding, deduplication, WebSocket
│   │   ├── agents/              # Detection, verification, orchestrator agents
│   │   ├── engine/              # Decision engine + XAI, prediction engine, resource commander
│   │   ├── pollers/             # Weather, seismic, social media pollers
│   │   ├── auth/                # JWT tokens + role-based dependencies
│   │   └── utils/               # Utility functions
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Backend tests
│   ├── seed.py                  # Demo data seeder
│   ├── requirements.txt
│   └── Dockerfile
├── scripts/                     # Utility scripts
│   └── download.sh              # Downloads fine-tuned NLP model weights
├── docs/                        # Project documentation & PRDs
│   └── architecture/            # Architecture documentation
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
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
python seed.py
uvicorn app.main:app --reload --port 8000
```

> No frontend step: the operator UI lives outside this repository.

---

## Resetting Demo Data

```bash
docker-compose exec backend python seed.py --reset
```