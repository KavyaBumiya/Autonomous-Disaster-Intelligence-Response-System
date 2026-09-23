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
├── frontend/                    # Vite + React + TypeScript (operator UI)
│   ├── public/                  # Static assets
│   ├── src/
│   │   ├── components/          # ResourcePanel, RouteIntelligence, VictimDetection…
│   │   ├── pages/               # CommandCenter, CriticalZone3D, LiveIncidentsPanel…
│   │   ├── hooks/               # Custom React hooks
│   │   ├── services/            # API services
│   │   ├── store/               # State management
│   │   ├── types/               # TypeScript types
│   │   ├── utils/               # Utility functions
│   │   └── assets/              # Images, icons
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── package.json
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
| Frontend  | http://localhost:3000      |
| API docs  | http://localhost:8000/docs |

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

# Frontend (operator UI)
cd frontend
npm install
npm run dev
```

---

## Resetting Demo Data

```bash
docker-compose exec backend python seed.py --reset
```