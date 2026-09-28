# AEGIS AI — Architecture Map

## Existing System (Pre-Phase 2)

### Backend Entrypoint
- `backend/app/main.py` — FastAPI app with Socket.IO ASGI middleware
- Routers mounted at `/api/*`
- Background pollers started on lifespan

### Core
- `app/core/config.py` — Pydantic Settings (env vars, .env files)
- `app/core/database.py` — Async SQLAlchemy engine + session factory
- `app/core/apis_config.py` — External API configuration constants

### Models (15 tables)
User, Zone, Report, Incident, AgentOutput, Resource, Action,
WeatherReading, SeismicEvent, SocialMediaPoll, AudioUpload,
Infrastructure, ExternalObservation, Evidence

### API Routers (21)
auth, reports, incidents, zones, actions, resources, predictions,
routes, earthquakes, command, phase2, heatmaps, weather, nasa,
maps, openai, firms, traffic, globe

### Services (23)
ai_gateway, clustering, conversation_store, damage_classification,
deduplication, evidence_fusion, geocoding, gis_service,
incident_narrative, moderation_service, nlp_service, object_detection,
phase2, prediction_service, report_parser, route_intelligence,
stt_service, trust_scoring, weather_service, websocket, whisper_stt

### Agents (5)
- `base.py` — AgentInput/AgentOutput contracts
- `detection.py` — Keyword-based disaster classification
- `verification.py` — Multi-signal trust scoring
- `victim_detection.py` — Image-based victim detection (MobileNetV2)
- `orchestrator.py` — Full intelligence pipeline

### Engine
- `decision.py` — Deterministic priority scoring (PRD §6 formula)
- `prediction_engine.py` — Flood/fire spread simulation
- `resource_commander.py` — Resource allocation

### Integrations
- `base.py` — BaseConnector (httpx, retry, circuit breaker)
- `registry.py` — Provider status tracking
- `cache.py` — Redis cache helpers
- `ai/nvidia_service.py` — NVIDIA NIM chat completions
- `ai/openai_service.py` — OpenAI connector
- `weather/` — Open-Meteo, MET Norway
- `seismic/` — USGS
- `gis/` — Overpass, OSRM
- `nasa/` — EONET, FIRMS
- `traffic/` — TomTom
- `globe/` — Cesium Ion

### Pollers
- weather (5min), seismic (2min), social (60s), eonet (10min)

### Auth
- JWT-based, demo mode (all users = commander)

### Infrastructure
- Docker: python:3.11-slim, ffmpeg, libpq
- docker-compose: db (PostGIS 15), redis (7-alpine), backend
- Alembic migrations (8 versions)

## Gap Analysis (What's Missing)

| Component | Status | Priority |
|-----------|--------|----------|
| AI Provider Abstraction | MISSING | P0 |
| Hugging Face Integration | MISSING | P0 |
| Model Registry | MISSING | P0 |
| Model Router | MISSING | P0 |
| NLP Pipeline Endpoint | MISSING | P0 |
| Image Analysis Pipeline Endpoint | MISSING | P0 |
| Prediction Engine API | PARTIAL | P1 |
| Explainability Endpoints | PARTIAL | P1 |
| Human Approval Layer | PARTIAL | P1 |
| Redis Queue Integration | PARTIAL | P1 |
| PostGIS Prediction Storage | MISSING | P1 |
| WebSocket Events (AI) | PARTIAL | P1 |
| Docker Productionization | PARTIAL | P2 |
| Testing (AI components) | MISSING | P0 |
| Monitoring/Observability | MISSING | P2 |

## Target Architecture

```
AEGIS AI
├── FastAPI (app/main.py)
│   ├── /api/ai/* — NEW: AI model serving endpoints
│   ├── /api/predictions/* — Existing + enhanced
│   ├── /api/decision/* — NEW: Human approval layer
│   └── /api/models/* — NEW: Model registry
├── AI Layer (NEW)
│   ├── providers/ — AIModelProvider abstraction
│   │   ├── huggingface_provider.py
│   │   ├── local_provider.py
│   │   └── openai_provider.py
│   ├── registry/ — Model registry
│   ├── router/ — Model router
│   ├── nlp/ — NLP pipeline
│   ├── vision/ — Image analysis pipeline
│   └── explain/ — Explainability
├── Agents (existing + new)
│   ├── detection, verification, victim_detection
│   ├── route_intelligence, resource_allocation
│   └── prediction, explainability
├── Engine (existing)
│   ├── decision.py — Deterministic scoring
│   └── prediction_engine.py — Flood/fire spread
├── Integrations (existing + new)
│   ├── base.py, registry.py, cache.py
│   ├── ai/ — NVIDIA, OpenAI, HuggingFace
│   └── data/ — Weather, Seismic, Satellite, GIS
└── Infrastructure
    ├── PostgreSQL/PostGIS — Persistent storage
    ├── Redis — Cache + queues
    └── Docker — Containerization
```
