# Product Requirements Document (PRD)
## AegisAI — Autonomous Disaster Intelligence & Response System

**Tagline:** "One AI. Every disaster. Every decision."
**Document type:** Hackathon PRD / Technical Proposal
**Version:** 2.0
**Status:** Implemented (MVP + Phase 2)

---

## 1. Executive Summary

AegisAI is an AI-first disaster response platform where artificial intelligence is the decision-making core of the system, not an add-on feature. The platform ingests multi-source data (satellite, drone, CCTV, weather, seismic, citizen reports, social media, IoT sensors), fuses it through a set of specialized AI agents, and outputs explainable, actionable decisions: who to rescue first, which team to send, which route to take, and what will happen next.

Where most disaster dashboards *display* information, AegisAI *decides* — and explains why — while keeping a human approver in the loop for high-stakes actions.

---

## 2. Problem Statement

- The UN estimates the number of people needing humanitarian assistance has nearly tripled in five years, heading toward 305M+.
- Current disaster response tooling is fragmented: satellite teams, weather teams, call centers, and NGOs often work off separate systems with no unified, real-time, prioritized view.
- Responders are frequently overwhelmed by report volume, unable to separate signal (a real, urgent case) from noise (duplicate, exaggerated, or fake reports).
- Decisions on resource allocation are usually manual, slow, and reactive rather than predictive.

**Core insight:** The bottleneck is not data collection — it's data fusion, verification, and decisioning under time pressure. That is exactly what AI is suited for.

---

## 3. Goals & Non-Goals

### Goals
- Build an AI decision layer that fuses heterogeneous data sources into prioritized, explainable actions.
- Provide a working real-time dashboard with 2D map visualization and live data overlays.
- Demonstrate graceful degradation: the system should keep working (in reduced form) when data sources or connectivity fail.
- Keep a human-in-the-loop for any action that risks life, safety, or major resource commitment.

### Non-Goals (be explicit about this in your pitch — judges respect scoping honesty)
- Not attempting to solve global-scale, production-grade national disaster infrastructure in a hackathon timeframe.
- Not claiming 100% accuracy on report verification or predictions — the system exposes confidence scores instead.
- Not replacing human incident commanders — augmenting and accelerating their decisions.

---

## 4. System Vision & Data Flow

```
Sensors / Citizens / Drones / Satellites / CCTV / Weather / Seismic / IoT
                        │
                        ▼
              AI BRAIN (Multi-Agent Layer)
   ┌─────────────┬─────────────┬─────────────┬─────────────┐
   │  Detection  │Verification │   Victim    │    Route    │
   │   Agent     │   Agent     │  Detection  │ Intelligence│
   ├─────────────┼─────────────┼─────────────┼─────────────┤
   │  Resource   │ Prediction  │ Behaviour   │ Volunteer   │
   │  Commander  │  Engine     │    AI       │    AI       │
   ├─────────────┴─────────────┴─────────────┴─────────────┤
   │              Explainability Layer (XAI)               │
   └─────────────────────────┬─────────────────────────────┘
                             ▼
                       DECISION ENGINE
         (priority scoring, resource allocation, routing)
                             ▼
                    EMERGENCY DASHBOARD
        (2D map, alerts, human approval UI, command center)
                             ▼
                Rescue Teams / NGOs / Volunteers
```

The dashboard is a **visualization and control surface for decisions the AI has already made** — not the thing generating them.

---

## 5. Feature Set (Detailed)

### 5.1 Citizen AI Assistant
- **What:** Multi-modal reporting — citizens submit text or voice reports of distress, damage, or needs.
- **How:** Speech-to-text (local Whisper `base` model) → NLP entity extraction (DistilBERT + spaCy NER) → image classification for damage severity.
- **Who it saves:** Citizens without access to formal emergency channels; enables reporting in local language and low-literacy contexts via voice.
- **Loophole solved:** Lack of structured, real-time ground-truth data feeding the system.
- **Status:** Implemented. Text reports via `POST /api/reports`, voice via `POST /api/reports/voice` (Whisper STT runs in background).

### 5.2 Disaster Detection Agent
- **What:** Classifies the type and severity of an unfolding disaster (flood, fire, earthquake, cyclone, landslide) from incoming multi-source data.
- **Inputs:** Citizen reports, social media posts, weather feeds (Open-Meteo), seismic sensor data (USGS), IoT flood sensors.
- **Output:** Disaster type, affected zone geometry, severity score (0-100), confidence.
- **Method:** Keyword frequency analysis + weather cross-check (rainfall >= 50mm/hr boosts flood, wind >= 80km/h boosts cyclone) + seismic cross-check (M >= 4.5 boosts earthquake).
- **Loophole solved:** Different disaster types need different detection logic; a single generic model underperforms — this agent routes each event to the correct downstream model.
- **Status:** Implemented as keyword-based classifier with multi-source cross-validation.

### 5.3 Report Verification Agent (Trust Scoring)
- **What:** Assigns every incoming report a confidence/trust score (0–100%) instead of treating all reports as equally credible.
- **Signals used (weighted formula):**
  - Corroboration (30%) — reports in same zone within 30 min
  - Source weight (15%) — citizen_text=0.75, citizen_voice=0.85, social_media=0.55
  - Weather consistency (20%) — does weather match claimed disaster type
  - Seismic consistency (15%) — USGS event within 50km for earthquake reports
  - Location coherence (10%) — GPS > NLP location > no location
  - Temporal plausibility (7%) — newer = higher
  - Novelty (3%) — MinHash similarity to recent reports (penalizes near-duplicates)
- **Example output:**
  - "Bridge collapsed" — Confidence 97% (14 corroborating reports, drone confirms, rainfall data supports flooding).
  - "Building on fire" — Confidence 28% (single report, no supporting evidence, weather data inconsistent).
- **Loophole solved:** Fake, exaggerated, or duplicate reports wasting rescue resources.
- **Status:** Fully implemented. Reports with trust < 25% are suppressed (not deleted).

### 5.4 Victim Detection Agent
- **What:** Estimates number and category of victims (trapped, injured, elderly, children) from drone imagery, thermal data, CCTV, and SOS signals.
- **Method:** Image analysis pipeline with hazard-specific routing (flood mapping / wildfire detection) → damage assessment → victim detection. Supports satellite, drone, photograph, and CCTV image types.
- **Loophole solved:** Manual headcounting is slow and error-prone in chaotic environments.
- **Status:** Implemented via image analysis pipeline (`POST /api/ai/analyze-image`).

### 5.5 Route Intelligence Agent
- **What:** Computes and continuously updates the safest, fastest route for rescue teams — disaster-aware routing.
- **Inputs:** Live road-block reports, flood-depth estimates, bridge risk scores, traffic data (TomTom), OSRM routing.
- **Loophole solved:** Standard maps don't account for disaster-specific hazards like flooded or collapsed roads; this agent recomputes routes as new information arrives.
- **Status:** Implemented via OSRM with disaster-aware weighting. `POST /api/routes/compute` returns primary + alternate routes.

### 5.6 Resource Commander (Decision Engine core)
- **What:** Converts prioritized needs into concrete, actionable instructions rather than raw availability numbers.
- **Method:** Assigns top-3 available resources by proximity (60%) + capacity (40%). Behaviour risk and supply urgency modifiers applied.
- **Example output:** "Send Team Bravo. Carry 70 food kits. Take Route C. ETA 17 min. Shelter B is full — redirect to Shelter C."
- **Loophole solved:** Most systems show *what's available*; almost none tell responders *what to do with it*.
- **Status:** Fully implemented. Creates pending_approval Action records. Emits WebSocket events for assignment + priority changes.

### 5.7 Prediction Engine
- **What:** Forecasts how the disaster will evolve using 5 hazard models:
  | Hazard | Model | Spatial Resolution |
  |---|---|---|
  | Flood | Cellular automata (rainfall-driven) | 12x12 grid |
  | Fire | Wind-directed buffer spread | Point-based |
  | Earthquake | Seismic shaking probability | Zone-uniform |
  | Landslide | Rainfall susceptibility | Zone-uniform |
  | Storm | Wind impact probability | Zone-uniform |
- **Interactive "what-if" simulation:** A commander can adjust parameters and see priority delta in real-time.
- **Loophole solved:** Reactive-only systems lose valuable response time; prediction lets teams pre-position resources.
- **Status:** Fully implemented. All models use real inputs (weather readings, USGS seismic data, GIS context) with honest fallback labels when data is unavailable.

### 5.8 Human Behaviour AI
- **What:** Estimates crowd movement, panic zones, and stampede/evacuation risk from CCTV/drone feeds and population density data.
- **Loophole solved:** Physical hazards aren't only environmental — crowd dynamics themselves cause casualties.
- **Status:** Implemented as explainable baseline at `POST /api/phase2/behaviour/assess`; scores crowd density, movement speed, exits, and distress reports.

### 5.9 Volunteer & NGO Coordinator
- **What:** Matches volunteer skills and location to the nearest, most relevant mission automatically.
- **Loophole solved:** Volunteer coordination is usually manual, slow, and inefficient.
- **Status:** Implemented as stateless skill-and-distance matcher at `POST /api/phase2/volunteers/match`.

### 5.10 Supply Chain Agent
- **What:** Predicts shortages (food, medicine, fuel, water) *before* they occur, based on consumption rate and incoming demand signals.
- **Loophole solved:** Shortages are typically discovered only after they happen.
- **Status:** Implemented as early-warning forecast at `POST /api/phase2/supply/forecast`; reports coverage, shortage risk, and reorder quantity.

### 5.11 Explainable AI (XAI) Layer
- **What:** Every priority score, allocation, or recommendation is accompanied by a human-readable justification.
- **Example:**
  > Zone A — Priority Score 94
  > • 52 distress reports
  > • Flood depth estimated at 1.8m
  > • 1 hospital inaccessible
  > • 37 elderly citizens detected
  > • Heavy rainfall expected in 2 hours
  > • Confidence: 97%
  > Recommended: 3 rescue boats, 2 ambulances, 15 medical kits
- **Loophole solved:** Responders won't trust or act on black-box AI output; transparency builds adoption.
- **Status:** Fully implemented. XAI reasoning stored per-incident, exposed via `GET /api/incidents/{id}` and `GET /api/command/explain/{id}`.

### 5.12 AI Command Center (Conversational Interface)
- **What:** A natural-language interface where a commander can ask questions and receive structured, explainable answers plus simulated outcomes.
- **Method:** NVIDIA NIM LLM (`nvidia/nemotron-3-ultra-550b-a55b`) with function-calling/tool-use. 16 deterministic tools available to the LLM.
- **Architecture constraint:** The LLM NEVER assigns priority scores or allocates resources — only the deterministic Decision Engine does. The LLM can only understand, summarize, explain, parse, and orchestrate tool calls.
- **Loophole solved:** Reduces the need to manually navigate dashboards during high-stress moments.
- **Status:** Fully implemented. `POST /api/command/query` for natural-language queries.

### 5.13 Emergency Dashboard (2D Map)
- **What:** The visualization layer — real-time 2D map showing damage heatmaps, resource positions, active routes, shelter capacity, and confidence-scored incidents.
- **Mapping:** Mapbox GL JS with dark theme. 6 toggleable data layers: flood extent, prediction cone, citizen reports, incidents, teams, shelters.
- **Realtime:** Socket.IO for live event-driven updates (13 event types). REST polling as source of truth (15-60s intervals).
- **Status:** Fully implemented. 10-page dashboard with Overview, Live Map, Incidents, Resources, Routes, Teams, Prediction Engine, Resource Commander, AI Assistant, and Flood Simulation.

### 5.14 IoT Flood Monitoring
- **What:** Network of IoT flood sensors reporting water level and flow velocity in real-time.
- **How:** Devices register via `POST /api/iot/v1/devices/register` (bootstrap token gated). Telemetry ingested via `POST /api/iot/v1/telemetry` (per-device bearer token auth). SHA-256 hashed tokens, constant-time comparison.
- **Risk assessment:** Rule-based thresholds on water level + flow velocity → NORMAL / WARNING / CRITICAL.
- **Status:** Fully implemented. Frontend Flood Simulation page supports both simulated and live IoT data sources.

### 5.15 Content Moderation
- **What:** Filters malicious content, prompt injection, abuse, and spam from citizen reports and social media.
- **Method:** Two-layer approach — deterministic regex patterns (Layer 1) + AI moderation via NVIDIA NIM (Layer 2).
- **Status:** Implemented. Flagged reports are suppressed with reduced trust score.

### 5.16 Social Media Ingestion
- **What:** Polls Twitter API v2 and Mastodon for disaster-related hashtags, NLP classifies posts, deduplicates via MinHash LSH, stores as reports.
- **Status:** Implemented. Polls every 60 seconds. 7 disaster hashtags tracked. Jaccard similarity threshold: 0.85.

### 5.17 Evidence Fusion
- **What:** Bundles 5 evidence sources (citizen reports, weather, seismic, infrastructure, predictions) into a unified evidence bundle per incident.
- **Status:** Fully implemented. Persists per-incident evidence rows for XAI attribution.

---

## 6. Loopholes & Solutions (Consolidated)

| # | Loophole | Problem | Solution |
|---|----------|---------|----------|
| 1 | No internet after disaster | Cell/fiber networks fail, cloud AI unreachable | Graceful degradation — system continues with cached data and local processing |
| 2 | Satellite images delayed | Overpasses take hours/days | Fuse drone, CCTV, IoT, and crowdsourced data as interim sources |
| 3 | Clouds block satellite optical imagery | Optical sensors can't see through cloud/smoke | Use SAR (Sentinel-1) which works day/night through cloud cover |
| 4 | CCTV unavailable in most zones | Rural/disaster areas often lack coverage | Treat CCTV as optional; prioritize drones + citizen photos/video |
| 5 | Every disaster type is different | One-size-fits-all models underperform | Modular AI: disaster-specific models selected by a central orchestrator |
| 6 | Real-time 3D mapping is expensive | Full 3D reconstruction is slow and costly | 2D GIS + AI overlays for the whole area; Cesium Ion token available for future 3D |
| 7 | Fake/misleading reports | Wastes rescue resources | Trust/confidence scoring via cross-referencing multiple signals |
| 8 | Inaccurate or missing GPS | Many reports lack precise location | NLP-based place-name extraction + geocoding + nearby-report correlation |
| 9 | AI misclassification | Wrong predictions send teams to wrong places | Human-in-the-loop approval for all high-risk/critical actions |
| 10 | High computation cost | Processing large-scale imagery/text in real time is expensive | Lightweight pretrained models; inference scoped only to affected regions |
| 11 | Data privacy | Victim data (photos, phone numbers, location) is sensitive | Encryption, anonymization, role-based access, auto-deletion post-emergency |
| 12 | Fragmented regional systems | Different countries/agencies use different formats | Standards-based API layer for GIS, emergency DB, and weather integration |
| 13 | No data in low-infrastructure regions | Sparse sensor/digital coverage | Hierarchical fallback: satellite → drone → crowdsourced → first-responder input |
| 14 | Dynamic/blocked roads | Roads become impassable without warning | Continuous re-routing using live drone/crowdsourced updates |
| 15 | Power failure | Devices lose power in the field | Low-power IoT devices with battery monitoring |

**Framing note for judges:** No system can eliminate every failure mode — networks fail, sensors break, AI makes mistakes. The credible pitch is not "we solved everything" but "we designed for graceful degradation, transparency, and human oversight at every failure point."

---

## 7. Tech Stack

### Frontend
- **Framework:** React 18 + TypeScript
- **Build tool:** Vite 6
- **Styling:** Tailwind CSS 3.4
- **Mapping:** Mapbox GL JS 3.31 (2D map with 6 data layers)
- **Realtime:** Socket.IO client 4.8
- **State management:** React Context + custom hooks (no external state library)
- **Charts:** Hand-rolled SVG/CSS (no charting library)
- **Icons:** lucide-react
- **Testing:** Vitest

### Backend
- **Framework:** FastAPI 0.110 (async, ASGI)
- **Server:** Uvicorn 0.29
- **Database:** PostgreSQL + SQLAlchemy 2.0 (async) + asyncpg
- **Migrations:** Alembic 1.13 (10 migrations)
- **Geospatial:** PostGIS via GeoAlchemy2 (POINT, POLYGON, GIST indexes)
- **Cache:** Redis 5.0 (async) — weather, geocode, route, social cursor
- **WebSocket:** python-socketio 5.11 (ASGI mount alongside FastAPI)
- **Task scheduler:** APScheduler 3.10 (AsyncIOScheduler)
- **Auth:** python-jose (JWT), passlib + bcrypt 4.0
- **Config:** pydantic-settings 2.2
- **HTTP client:** httpx 0.28+ (all external APIs + NVIDIA NIM)
- **NLP/ML:** transformers 4.40, torch 2.0+, torchvision, langdetect, spaCy
- **Deduplication:** datasketch 1.6 (MinHash LSH)
- **Social:** tweepy 4.14 (Twitter API v2)
- **Geocoding:** geopy 2.4 (Nominatim), Photon (Komoot)
- **Geometry:** shapely 2.0
- **Logging:** structlog 24.1
- **Retry:** tenacity 8.3
- **Testing:** pytest 8.0+, pytest-asyncio, respx

### AI / ML Layer
- **LLM orchestration:** NVIDIA NIM (`nvidia/nemotron-3-ultra-550b-a55b`) via OpenAI-compatible API — command query, report parsing, translation, moderation, summarization
- **Speech-to-text:** Local Whisper (`base` model) — openai-whisper
- **NLP classification:** DistilBERT multi-label transformer with keyword fallback
- **NER/location extraction:** spaCy with custom entity ruler for Vadodara landmarks
- **Image analysis:** HuggingFace models for flood mapping, wildfire detection, damage assessment, victim detection
- **Model router:** Routes inference to best provider (HuggingFace, Local, NVIDIA NIM) based on task, hazard, latency, hardware
- **Trust scoring:** Deterministic weighted formula (7 signals)
- **Prediction models:** Cellular automata (flood), wind-directed buffer (fire), seismic probability (earthquake), rainfall susceptibility (landslide), wind impact (storm)

### Infrastructure
- **Containerization:** Docker + docker-compose
- **Deployment:** Render (backend), Vercel (frontend)
- **Monitoring:** Health endpoints (`/healthz`, `/readyz`, `/api/health`)
- **Circuit breaker:** After 3 consecutive failures, provider calls skipped for 60s
- **Redis caching:** Weather (5min), forecast (30min), geocode (24h), routes (10min), social cursor (7 days)

---

## 8. APIs & Data Sources

### API Endpoints (Implemented)

| Category | Method | Path | Purpose |
|---|---|---|---|
| Health | GET | `/api/health` | Full health: providers, DB, cache status |
| Health | GET | `/healthz` | Process liveness (no DB/cache) |
| Health | GET | `/readyz` | Readiness — DB reachable |
| Reports | POST | `/api/reports` | Ingest text citizen report |
| Reports | POST | `/api/reports/voice` | Ingest voice audio (Whisper STT) |
| Reports | GET | `/api/reports` | List reports (filter by zone, source, trust) |
| Incidents | GET | `/api/incidents` | List incidents |
| Incidents | GET | `/api/incidents/{id}` | Incident detail with XAI reasoning |
| Zones | POST | `/api/zones` | Create/update zone |
| Zones | GET | `/api/zones` | List zones |
| Zones | GET | `/api/zones/{id}` | Zone detail |
| Zones | GET | `/api/zones/{id}/reports/summary` | Aggregated report stats |
| Actions | PATCH | `/api/actions/{id}` | Commander approves/rejects pending action |
| Resources | GET | `/api/resources` | List resources |
| Resources | POST | `/api/resources` | Register new resource |
| Resources | POST | `/api/resources/{id}/assign-resources` | Auto-assign resources |
| Resources | PUT | `/api/resources/{id}` | Update resource availability |
| Predictions | POST | `/api/predictions/flood` | Flood spread simulation |
| Predictions | POST | `/api/predictions/fire` | Fire spread simulation |
| Predictions | GET | `/api/predictions/all/{zone_id}` | All 5 hazard projections |
| Predictions | POST | `/api/predictions/what-if` | What-if scenario |
| Routes | POST | `/api/routes/compute` | Disaster-aware routing |
| Earthquakes | GET | `/api/earthquakes/recent` | Recent seismic events |
| Weather | GET | `/api/weather/current` | Current conditions + risk score |
| Weather | GET | `/api/weather/forecast` | Hourly forecast |
| NASA | GET | `/api/nasa/eonet/events` | EONET natural events |
| NASA FIRMS | GET | `/api/firms/fires` | Active fires |
| Maps | GET | `/api/maps/geocode` | Forward geocoding |
| Maps | GET | `/api/maps/reverse-geocode` | Reverse geocoding |
| OpenAI | POST | `/api/openai/analyze-disaster` | Disaster analysis |
| OpenAI | POST | `/api/openai/chat` | Chat completion |
| TomTom | GET | `/api/traffic/route` | Route with traffic |
| Cesium | GET | `/api/globe/token` | Cesium Ion token |
| AI | POST | `/api/ai/analyze-report` | Full NLP report analysis |
| AI | POST | `/api/ai/analyze-image` | Image analysis pipeline |
| AI | POST | `/api/ai/classify-hazard` | Quick hazard classification |
| AI | POST | `/api/ai/verify-report` | Report credibility verification |
| AI | POST | `/api/ai/explain` | Explainability |
| AI | GET | `/api/ai/models` | List registered models |
| Command | POST | `/api/command/query` | Natural-language commander query |
| Command | GET | `/api/command/explain/{id}` | XAI explanation |
| Command | GET | `/api/command/summarise/{id}` | Operational summary |
| Command | GET | `/api/command/approval-queue` | Pending actions |
| Decision | POST | `/api/decision/recommend` | AI generates recommendation |
| Decision | POST | `/api/decision/approve` | Human approves |
| Decision | POST | `/api/decision/reject` | Human rejects |
| Phase 2 | POST | `/api/phase2/behaviour/assess` | Crowd behaviour risk |
| Phase 2 | POST | `/api/phase2/supply/forecast` | Supply shortage forecast |
| Phase 2 | POST | `/api/phase2/volunteers/match` | Volunteer matching |
| Heatmaps | GET | `/api/heatmaps/priority` | Priority score heatmap |
| Heatmaps | GET | `/api/heatmaps/victim-density` | Victim density heatmap |
| Heatmaps | GET | `/api/heatmaps/trust-score` | Trust score heatmap |
| Heatmaps | GET | `/api/heatmaps/combined` | All metrics |
| IoT | POST | `/api/iot/v1/devices/register` | Register flood device |
| IoT | POST | `/api/iot/v1/telemetry` | Ingest flood telemetry |
| IoT | GET | `/api/iot/v1/devices/{id}/history` | Telemetry history |

### Data Sources

| Category | Source | Use |
|---|---|---|
| Weather | Open-Meteo (primary), MET Norway (fallback) | Rainfall prediction, storm tracking |
| Seismic | USGS Earthquake API | Earthquake magnitude/location feeds |
| Geocoding | Nominatim (primary), Photon/Komoot (fallback) | Forward/reverse geocoding |
| GIS/OSM | Overpass API | Infrastructure (hospitals, shelters, roads) |
| Routing | OSRM | Disaster-aware route planning |
| Traffic | TomTom | Route, flow, search |
| Satellite | NASA EONET v3 | Natural event catalog |
| Satellite | NASA FIRMS (VIIRS/MODIS) | Active fire detection |
| 3D Terrain | Cesium Ion | 3D globe imagery/terrain (token available) |
| Social | Twitter API v2, Mastodon | Crowd-sourced situational reports |
| AI | NVIDIA NIM | LLM (command query, report parsing, translation, moderation) |
| AI | HuggingFace | Hazard classification, flood mapping, wildfire detection, damage assessment |
| IoT | Custom flood sensors | Water level, flow velocity monitoring |

---

## 9. Architecture Summary

```
[Data Sources] → [Ingestion API Layer] → [Agent Orchestrator]
       → [Specialized AI Agents: Detection / Verification / Victim /
          Route / Resource / Prediction / Behaviour / Volunteer / Supply]
       → [Decision Engine + XAI Layer]
       → [PostgreSQL/PostGIS + Redis]
       → [Socket.IO layer] → [React Dashboard: 2D map, alerts, command center]
       → [Human approval] → [Action dispatched to rescue teams/NGOs]
```

### Key Architecture Patterns
- **LLM constraint:** The AI layer may ONLY understand, summarize, explain, parse, and orchestrate tool calls. It NEVER assigns priority scores, allocates resources, or authorises dispatch.
- **Deterministic core:** All safety-critical numbers come from the Decision Engine, not the LLM.
- **Human approval gate:** All critical actions require commander approval via `PATCH /api/actions/{id}`.
- **Graceful degradation:** Every external provider failure is caught, logged, and surfaced as DEGRADED — never fabricated.
- **Circuit breaker:** After 3 consecutive failures, provider calls are skipped for 60s.
- **Idempotency:** IoT telemetry uses `event_id` for deduplication; social posts use exact ID + MinHash.

---

## 10. Human-in-the-Loop & Ethics

- All **critical, resource-committing, or life-safety actions require human approval** before execution — AI recommends, humans confirm.
- Every report/prediction carries a **visible confidence score**; nothing is presented as certain.
- **Privacy:** personal data is encrypted at rest and in transit, access is role-based, and non-essential personal data is purged after the emergency window closes.
- **Bias awareness:** detection/verification models should be evaluated for performance gaps across regions/languages.

---

## 11. Success Metrics

- **Response time reduction:** time from report received → resource dispatched, vs. baseline manual process
- **Report triage accuracy:** % of high-priority zones correctly identified in simulated scenarios
- **False positive rate:** fake/low-value reports correctly down-weighted
- **Coverage under degraded conditions:** system still functions (in reduced form) when connectivity/data sources are cut
- **User trust/explainability score:** qualitative feedback on whether the reasoning shown is understandable and actionable

---

## 12. Build Phases

### Phase 0 — Setup (Hours 0–4)
- Repo scaffolding, tech stack setup, data source access (API keys), sample dataset collection.

### Phase 1 — Core Data Pipeline (Hours 4–14)
- Citizen report ingestion (text/voice), NLP location extraction, database schema (PostGIS), base 2D map rendering.

### Phase 2 — AI Agents MVP (Hours 14–28)
- Disaster Detection Agent, Report Verification (trust scoring), basic Victim Detection (image-based), Decision Engine v1 (priority scoring + XAI text output).

### Phase 3 — Decisioning & Routing (Hours 28–36)
- Resource Commander logic, Route Intelligence (basic re-routing on blocked-road input), Prediction Engine v1 (simple flood/fire spread simulation), what-if simulation UI.

### Phase 4 — Dashboard & Realtime (Hours 36–42)
- Full dashboard integration, heatmaps, live WebSocket updates, 10-page UI with all visualization layers.

### Phase 5 — Command Center & Polish (Hours 42–46)
- Conversational AI Command Center (NVIDIA NIM + function calling into the Decision Engine), UI polish, IoT flood sensor integration.

### Phase 6 — Demo Prep (Hours 46–48)
- Scripted simulated disaster scenario (e.g., Vadodara flood), rehearsal of the full report → detection → verification → decision → dispatch flow, backup recorded demo.

---

## 13. Demo Script (Suggested)

1. A simulated citizen uploads a voice message: "Five people trapped near XYZ School."
2. Whisper STT transcribes the audio; NLP extracts location and classifies flood severity.
3. Weather API shows heavy rainfall expected in the next 2 hours.
4. System assigns a trust score to the report based on corroboration, weather consistency, and location coherence.
5. Decision Engine assigns a priority score to the zone with full XAI reasoning shown on screen.
6. Resource Commander recommends a specific team, route, and ETA.
7. Commander asks the AI Command Center: "What if rainfall increases 30%?" — system shows projected new flood zones and shelter overflow.
8. Human operator approves the dispatch; dashboard updates live with the rescue team en route on the 2D map.
9. IoT flood sensor shows rising water level → system updates prediction and alerts commander.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Erroneous AI alerts misdirect rescue teams | Confidence scores + human approval gate for critical actions |
| Reliance on internet/cloud APIs during demo | Prepare an offline/local-fallback demo path and recorded backup |
| Real satellite/drone data unavailable for live demo | Use public historical disaster datasets to simulate the live scenario convincingly |
| Overscoping for a 48-hour hackathon | Prioritize Phases 1–4 as the "must-have" MVP; treat Command Center and IoT as stretch goals |
| Privacy concerns with real citizen data | Use synthetic/anonymized data for the demo, never real personal data |

---

## 15. Team Roles (Suggested Split)

- **AI/ML engineer(s):** Detection, verification, prediction models, NVIDIA NIM integration
- **Backend engineer:** FastAPI layer, orchestrator, PostgreSQL/PostGIS, Socket.IO, pollers
- **Frontend engineer:** React dashboard, Mapbox GL integration, realtime updates
- **Data/GIS specialist:** Dataset sourcing, geospatial pipeline, PostGIS
- **Product/Pitch lead:** Demo script, slides, framing the "graceful degradation" narrative for judges

---

## 16. Closing Note for the Pitch

The single strongest differentiator to emphasize to judges is the shift from **"AI as a data-labeling add-on"** to **"AI as the decision-maker, with humans approving high-stakes actions and every recommendation explained."** Most competing hackathon disaster projects stop at a dashboard with a heatmap. AegisAI's edge is the Decision Engine + Resource Commander + Explainable AI layer, plus honest handling of failure modes (offline operation, confidence scoring, graceful degradation) rather than a claim that every loophole is fully closed.
