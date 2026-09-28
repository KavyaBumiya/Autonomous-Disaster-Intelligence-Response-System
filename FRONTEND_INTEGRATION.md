# AegisAI Frontend Integration Guide

## Base URL

```
Production: https://autonomous-disaster-intelligence.onrender.com
Local:      http://localhost:8000
```

All endpoints are prefixed with `/api`. The backend runs **unauthenticated** — no tokens, no cookies, no sign-in. Every request just works.

---

## Quick Start

```typescript
const API = "https://autonomous-disaster-intelligence.onrender.com/api";

// Fetch zones
const res = await fetch(`${API}/zones`);
const { zones } = await res.json();

// Create a zone
await fetch(`${API}/zones`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "India",
    centroid_lat: 20.5937,
    centroid_lng: 78.9629,
    radius_meters: 1000000,
    density_ratio: 0.5,
  }),
});

// Connect to live feed
import { io } from "socket.io-client";
const socket = io("https://autonomous-disaster-intelligence.onrender.com");
socket.on("new_incident", (data) => console.log("New incident:", data));
```

---

## Health & Monitoring

### GET `/api/health`
Returns service status. Poll this to show a degraded banner.

```json
{
  "status": "ok | degraded",
  "version": "1.0.0",
  "build": "unversioned",
  "providers": {
    "weather": { "status": "ONLINE", "canonical": true },
    "seismic": { "status": "ONLINE", "canonical": true },
    "ai": { "status": "OFFLINE", "canonical": true }
  },
  "services": {
    "database": "ONLINE",
    "cache": "ONLINE"
  },
  "reasons": []
}
```

### GET `/api`
```json
{
  "name": "AegisAI API",
  "description": "AI-powered disaster intelligence & response platform",
  "version": "1.0.0",
  "status": "operational",
  "docs": "/docs",
  "health": "/api/health"
}
```

---

## Zones

Zones are operator-declared geography. Create them via the API — they are NOT seeded.

### GET `/api/zones`
Query: `limit` (default 100, max 500), `offset` (default 0)

```json
{
  "zones": [
    {
      "zone_id": "uuid",
      "name": "India",
      "centroid_lat": 20.5937,
      "centroid_lng": 78.9629,
      "radius_meters": 1000000.0,
      "density_ratio": 0.5,
      "priority_score": 0,
      "victim_count": 0,
      "created_at": "2026-09-28T16:04:51.785124+00:00"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

### POST `/api/zones`
Idempotent on name — re-posting updates geometry instead of duplicating.

Body:
```json
{
  "name": "India",           // required, 1-255 chars
  "centroid_lat": 20.5937,    // required, -90 to 90
  "centroid_lng": 78.9629,    // required, -180 to 180
  "radius_meters": 1000000,   // optional, default 500, max 200000
  "density_ratio": 0.5        // optional, 0.0-1.0
}
```

Response (201):
```json
{
  "zone_id": "uuid",
  "name": "India",
  "centroid_lat": 20.5937,
  "centroid_lng": 78.9629,
  "radius_meters": 1000000.0,
  "density_ratio": 0.5,
  "priority_score": 0,
  "victim_count": 0,
  "created": true,
  "created_at": "2026-09-28T16:04:51.785124+00:00"
}
```

### GET `/api/zones/{zone_id}`
```json
{
  "zone_id": "uuid",
  "name": "India",
  "centroid_lat": 20.5937,
  "centroid_lng": 78.9629,
  "radius_meters": 1000000.0,
  "density_ratio": 0.5,
  "priority_score": 0,
  "victim_count": 0,
  "created_at": "2026-09-28T16:04:51.785124+00:00",
  "updated_at": "2026-09-28T16:04:51.785124+00:00"
}
```

### GET `/api/zones/{zone_id}/reports/summary`
```json
{
  "zone_id": "uuid",
  "total_reports": 42,
  "high_trust_count": 10,
  "medium_trust_count": 15,
  "low_trust_count": 12,
  "suppressed_count": 5,
  "sources": {
    "citizen_text": 20,
    "citizen_voice": 5,
    "social_media": 17
  },
  "dominant_disaster_type": "flood",
  "avg_trust_score": 0.72
}
```

---

## Incidents

### GET `/api/incidents`
Query: `active_only` (bool, default true), `zone_id`, `limit` (default 50, max 200), `offset`

```json
{
  "incidents": [
    {
      "incident_id": "uuid",
      "zone_id": "uuid",
      "zone_name": "India",
      "lat": 20.5937,
      "lng": 78.9629,
      "disaster_type": "flood",
      "priority_score": 75.0,
      "priority_band": "HIGH",
      "severity_score": 60.0,
      "confidence": 0.85,
      "status": "active",
      "report_count": 12,
      "avg_trust_score": 0.72,
      "victim_count": 50,
      "victim_confidence": 0.8,
      "xai_reasoning": "string",
      "groq_summary": "string",
      "groq_explanation": "string",
      "active": true,
      "created_at": "2026-09-28T16:04:51.785124+00:00",
      "updated_at": "2026-09-28T16:04:51.785124+00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### GET `/api/incidents/{incident_id}`
Returns a single incident object (same shape as above).

---

## Reports

### GET `/api/reports`
Query: `zone_id`, `source`, `min_trust` (default 0.25), `include_suppressed` (bool, default false), `limit` (default 50, max 200), `offset`

```json
{
  "reports": [
    {
      "report_id": "uuid",
      "zone_id": "uuid",
      "source": "citizen_text",
      "trust_score": 0.85,
      "suppressed": false,
      "disaster_type": "flood",
      "informative": true,
      "summary": "First 140 chars of message...",
      "lat": 20.5937,
      "lng": 78.9629,
      "language_code": "en",
      "nlp_model_version": "v1_distilbert",
      "created_at": "2026-09-28T16:04:51.785124+00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### POST `/api/reports`
Submit a text report.

Body:
```json
{
  "message_text": "Flood water rising near the river",  // required
  "reporter_id": "user-123",                           // optional
  "location_string": "Vadodara, India",               // optional
  "lat": 22.3072,                                     // optional
  "lng": 73.1812,                                     // optional
  "device_type": "mobile"                             // optional
}
```

Response (201):
```json
{
  "report_id": "uuid",
  "status": "created",
  "source": "citizen_text",
  "suppressed": false
}
```

### POST `/api/reports/voice`
Submit a voice report. `multipart/form-data`:

| Field | Type | Required |
|-------|------|----------|
| `audio_file` | File | Yes (wav/mpeg/ogg/mp4, max 10MB) |
| `reporter_id` | string | No |
| `location_string` | string | No |
| `lat` | float | No |
| `lng` | float | No |

Response (202):
```json
{
  "report_id": "uuid",
  "status": "processing",
  "source": "citizen_voice",
  "transcript": null,
  "stt_provider": "local",
  "message": "Audio received. Transcription in progress."
}
```

---

## Resources

### GET `/api/resources`
Query: `resource_type` (team|vehicle|supply|shelter), `zone_id`, `available` (bool)

```json
{
  "resources": [
    {
      "resource_id": "uuid",
      "name": "Team Alpha",
      "resource_type": "team",
      "capacity": 4,
      "current_load": 0,
      "available": true,
      "lat": 22.3072,
      "lng": 73.1812,
      "assigned_zone_id": "uuid"
    }
  ],
  "total": 1
}
```

### POST `/api/resources`
`application/x-www-form-urlencoded`:

| Field | Type | Required |
|-------|------|----------|
| `name` | string | Yes |
| `resource_type` | string | Yes (team|vehicle|supply|shelter) |
| `capacity` | int | No (default 1) |
| `lat` | float | No |
| `lng` | float | No |

Response (201):
```json
{
  "resource_id": "uuid",
  "name": "Team Alpha",
  "resource_type": "team",
  "capacity": 4,
  "current_load": 0,
  "available": true,
  "message": "Resource created"
}
```

### PUT `/api/resources/{resource_id}`
Body: `{ "available": true, "current_load": 2 }` (both optional)

### POST `/api/resources/{incident_id}/assign-resources`
Auto-assigns resources to an incident. Returns:
```json
{
  "incident_id": "uuid",
  "assigned_resources": ["uuid"],
  "action_id": "uuid",
  "priority_score": 75.0,
  "message": "Resources assigned"
}
```

---

## Weather

### GET `/api/weather/current`
Query: `lat` (required), `lng` (required)

```json
{
  "provider": "open-meteo",
  "lat": 22.3072,
  "lng": 73.1812,
  "rainfall_mm_hr": 5.2,
  "wind_speed_kmh": 15.0,
  "temperature_c": 28.0,
  "humidity_pct": 75.0,
  "weather_main": "Rain",
  "weather_description": "moderate rain",
  "risk_score": 0.45,
  "timestamp": "2026-09-28T16:04:51.785124+00:00",
  "from_cache": false,
  "source": "current"
}
```

### GET `/api/weather/forecast`
Query: `lat` (required), `lng` (required), `hours` (1-48, default 24)

```json
{
  "provider": "open-meteo",
  "lat": 22.3072,
  "lng": 73.1812,
  "hours": 24,
  "retrieved_at": "2026-09-28T16:04:51.785124+00:00",
  "from_cache": false,
  "source": "forecast"
}
```

---

## Predictions

### POST `/api/predictions/flood`
```json
{
  "zone_id": "uuid",
  "hours": 12,
  "rainfall_mm_hr": 50.0
}
```

### POST `/api/predictions/fire`
```json
{
  "zone_id": "uuid",
  "hours": 12,
  "wind_speed_kmh": 20.0
}
```

### POST `/api/predictions/what-if`
```json
{
  "zone_id": "uuid",
  "disaster_type": "flood",
  "rainfall_mm_hr": 50.0,
  "hours": 12,
  "wind_speed_kmh": 20.0,
  "resource_delta": 0
}
```

### GET `/api/predictions/{zone_id}`
```json
{
  "zone_id": "uuid",
  "zone_name": "India",
  "projection_label": "MODEL PROJECTION",
  "last_flood": {
    "expires_at": "2026-09-28T17:04:51.785124+00:00",
    "affected_cells": [],
    "max_intensity": 0,
    "flooded_percentage": 0
  },
  "last_fire": {
    "expires_at": "2026-09-28T17:04:51.785124+00:00",
    "burned_area": [],
    "max_intensity": 0,
    "spread_direction_degrees": 0.0
  }
}
```

---

## Decision Engine

### POST `/api/decision/recommend`
```json
{
  "incident_id": "uuid",
  "action_type": "dispatch",
  "context": {},
  "hazard_type": "flood",
  "location": { "lat": 22.3072, "lng": 73.1812 }
}
```

Response:
```json
{
  "decision_id": "uuid",
  "incident_id": "uuid",
  "action_type": "dispatch",
  "recommendation": "Deploy Team Alpha to zone...",
  "confidence": 0.85,
  "evidence": {},
  "explanation": "string",
  "model_used": "decision-engine-v1",
  "model_version": "1.0.0",
  "requires_human_approval": true,
  "status": "pending_approval",
  "created_at": "2026-09-28T16:04:51.785124+00:00"
}
```

### POST `/api/decision/approve`
```json
{ "decision_id": "uuid", "note": "Approved for dispatch" }
```

### POST `/api/decision/reject`
```json
{ "decision_id": "uuid", "reason": "Insufficient resources" }
```

### GET `/api/decision/pending`
```json
{
  "pending_count": 1,
  "decisions": [
    {
      "decision_id": "uuid",
      "incident_id": "uuid",
      "zone_id": "uuid",
      "action_type": "dispatch",
      "description": "string",
      "recommended_by": "decision-engine",
      "priority_score": 75.0,
      "status": "pending_approval",
      "created_at": "2026-09-28T16:04:51.785124+00:00"
    }
  ]
}
```

---

## Command Center (AI)

### POST `/api/command/query`
```json
{
  "user_query": "What is the flood risk in Zone 1?",
  "model_name": null,
  "conversation_id": "conv-123",
  "include_xai": true,
  "zone_context": "uuid"
}
```

Response:
```json
{
  "response": "AI analysis result...",
  "function_calls": [],
  "execution_results": [],
  "execution_time": 1.23,
  "model_used": "nvidia/nemotron-3-ultra-550b-a55b",
  "ai_available": true,
  "ai_configured": true,
  "ai_call_id": "uuid",
  "conversation_id": "conv-123"
}
```

### GET `/api/command/health`
```json
{
  "ai_available": true,
  "ai_configured": true,
  "model": "nvidia/nemotron-3-ultra-550b-a55b",
  "provider": "nvidia-nim",
  "note": "string"
}
```

### GET `/api/command/critical`
Query: `threshold` (0-100, default 70), `limit` (1-50, default 10)

### GET `/api/command/resources/available`
```json
{
  "resources": [],
  "total": 0,
  "availability_ratio": 0.0
}
```

### GET `/api/command/zone-status`
Query: `zone_id` (required)

### GET `/api/command/approval-queue`
```json
{
  "pending_count": 0,
  "actions": [],
  "note": "string"
}
```

---

## AI Endpoints

### POST `/api/ai/analyze-report`
```json
{
  "text": "Severe flooding in Vadodara, water rising fast, people trapped",
  "hazard_hint": "flood",
  "preferred_provider": null
}
```

### POST `/api/ai/classify-hazard`
```json
{
  "text": "The city is flooded due to heavy rainfall",
  "hazard_hint": null,
  "preferred_provider": null
}
```

### POST `/api/ai/verify-report`
```json
{
  "text": "Flood water rising near the river",
  "source": "citizen_text",
  "location": { "lat": 22.3072, "lng": 73.1812 }
}
```

Response:
```json
{
  "credibility_score": 0.85,
  "hazard_type": "flood",
  "hazard_confidence": 0.9,
  "explanation": "string",
  "fallback_used": false
}
```

### POST `/api/ai/summarize`
```json
{
  "text": "Long text to summarize...",
  "max_length": 200,
  "preferred_provider": null
}
```

### GET `/api/ai/providers`
```json
{
  "nvidia": { "status": "ONLINE", "models_available": 100 },
  "huggingface": { "status": "OFFLINE" },
  "local": { "status": "ONLINE", "torch_version": "2.14.0+cpu" }
}
```

### GET `/api/ai/health`
```json
{
  "status": "ok",
  "providers": { "nvidia": { "status": "ONLINE" } },
  "models_registered": 100
}
```

---

## External Data Sources

### GET `/api/earthquakes/recent`
Query: `minutes` (1-20160, default 1440), `min_magnitude` (0-10, default 0), `limit` (1-200, default 50)

### GET `/api/nasa/eonet/events`
Query: `status` (open|all|closed), `category`, `limit` (1-500, default 100), `lat`, `lng`, `radius_km` (default 250)

### GET `/api/firms/fires`
Query: `lat` (required), `lng` (required), `radius_km` (1-5000, default 500), `days` (1-10, default 7)

### GET `/api/weather/current`
Query: `lat` (required), `lng` (required)

### GET `/api/maps/geocode`
Query: `address` (required)

### GET `/api/maps/reverse-geocode`
Query: `lat` (required), `lng` (required)

### GET `/api/traffic/flow`
Query: `lat` (required), `lng` (required), `zoom` (0-22, default 10)

---

## WebSocket (Socket.IO)

Connect to the same origin as the REST API:

```typescript
import { io } from "socket.io-client";

const socket = io("https://autonomous-disaster-intelligence.onrender.com");

socket.on("connect", () => {
  console.log("Connected to live feed");
  socket.emit("subscribe", { room: "global_feed" });
});

socket.on("new_incident", (data) => {
  console.log("New incident:", data);
});

socket.on("new_report", (data) => {
  console.log("New report:", data);
});
```

### Client-to-Server Events

| Event | Payload | Description |
|-------|---------|-------------|
| `subscribe` | `{ "room": "global_feed" \| "zone_<id>" }` | Join a room |
| `unsubscribe` | `{ "room": "global_feed" \| "zone_<id>" }` | Leave a room |

### Server-to-Client Events

| Event | Payload | Description |
|-------|---------|-------------|
| `connected` | `{ "message": "Connected to AegisAI live feed" }` | Connection confirmed |
| `subscribed` | `{ "room": "<room_name>" }` | Subscription confirmed |
| `new_report` | `{ report_id, source, trust_score, suppressed, disaster_type, lat, lng, summary_text }` | New citizen report |
| `new_incident` | `{ incident_id, zone_id, lat, lng, disaster_type, priority_score }` | New incident detected |
| `incident_priority_updated` | `{ incident_id, zone_id, old_priority, new_priority, xai_string, disaster_type }` | Priority changed |
| `action_state_changed` | `{ action_id, zone_id, new_status, changed_by_role }` | Action approved/rejected |
| `prediction_updated` | `{ zone_id, disaster_type, result }` | New prediction available |
| `resource_assigned` | `{ action_id, zone_id, resources }` | Resources assigned to incident |
| `resource_status_updated` | `{ resource_id, zone_id, available, current_load, capacity }` | Resource status changed |
| `route_changed` | `{ zone_id, route_data }` | Route updated |
| `weather_updated` | `{ zone_id, risk_score, previous_risk_score, rainfall_mm_hr, wind_speed_kmh, weather_main, weather_description }` | Weather update |
| `earthquake_detected` | `{ count, events }` | Seismic activity detected |
| `command_interaction` | `{ user_id, query, response }` | AI command response |
| `trust_score_updated` | `{ report_id, old_trust_score, new_trust_score, reasoning_delta }` | Trust score changed |
| `evidence_updated` | `{ incident_id, zone_id, ...bundle_summary }` | Evidence bundle updated |

---

## Error Handling

All errors return JSON:
```json
{ "detail": "Error message" }
```

Common status codes:
- `400` — Bad request (validation error)
- `404` — Resource not found
- `422` — Validation error (Pydantic)
- `502` — External provider unavailable
- `503` — Service unavailable (e.g., weather provider down)

---

## CORS

The backend allows all origins by default (`FRONTEND_ORIGIN` is empty = wildcard). No CORS issues expected.

---

## Rate Limiting

None. No rate-limiting middleware is configured.

---

## Authentication

None. The deployment runs unauthenticated. Every route is open. The `Authorization` header is ignored.
