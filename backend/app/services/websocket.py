"""
Socket.IO server and event emitter.
All five Phase 1 event types are defined here.
The `sio` instance is imported into main.py for ASGI mounting.
"""
from datetime import datetime, timezone

import socketio
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()

# Async Socket.IO server. Origins mirror the REST CORS policy so the console can
# be deployed on a different host than the API: FRONTEND_ORIGIN (comma-separated)
# restricts both, and an empty value keeps the permissive local-demo default.
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=get_settings().cors_origins,
    logger=False,
    engineio_logger=False,
)


# ── Connection lifecycle ──────────────────────────────────────

@sio.event
async def connect(sid, environ, auth):
    logger.info("WebSocket client connected", sid=sid)
    await sio.emit("connected", {"message": "Connected to AegisAI live feed"}, to=sid)


@sio.event
async def disconnect(sid):
    logger.info("WebSocket client disconnected", sid=sid)


@sio.event
async def subscribe(sid, data):
    """Client subscribes to a room: { room: 'global_feed' | 'zone_<id>' }"""
    room = data.get("room", "global_feed")
    await sio.enter_room(sid, room)
    logger.info("Client subscribed to room", sid=sid, room=room)
    await sio.emit("subscribed", {"room": room}, to=sid)


@sio.event
async def unsubscribe(sid, data):
    room = data.get("room", "global_feed")
    await sio.leave_room(sid, room)


# ── Event emitters ────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def emit_new_report(report: dict) -> None:
    """
    Fired after a report is stored.
    Payload: { report_id, source, trust_score, disaster_type, lat, lng, summary_text }
    """
    payload = {
        "event": "new_report",
        "payload": {
            "report_id": report.get("id"),
            "source": report.get("source"),
            "trust_score": report.get("trust_score"),
            "suppressed": report.get("suppressed", False),
            "disaster_type": report.get("disaster_type"),
            "lat": report.get("lat"),
            "lng": report.get("lng"),
            "summary_text": (report.get("message_text") or report.get("transcript") or "")[:140],
        },
        "timestamp": _now(),
        "source": "ingestion_service",
    }
    await sio.emit("new_report", payload, room="global_feed")
    if report.get("zone_id"):
        await sio.emit("new_report", payload, room=f"zone_{report['zone_id']}")


async def emit_trust_score_updated(report_id: str, old_score: float, new_score: float, reasoning: str) -> None:
    """Fired when the Verification Agent re-scores a report."""
    payload = {
        "event": "trust_score_updated",
        "payload": {
            "report_id": report_id,
            "old_trust_score": old_score,
            "new_trust_score": new_score,
            "reasoning_delta": reasoning,
        },
        "timestamp": _now(),
        "source": "verification_agent",
    }
    await sio.emit("trust_score_updated", payload, room="global_feed")


async def emit_incident_priority_updated(zone_id: str, incident_id: str, old_priority: float,
                                          new_priority: float, xai_string: str,
                                          disaster_type: str | None) -> None:
    """Fired when the Decision Engine re-scores a zone."""
    payload = {
        "event": "incident_priority_updated",
        "payload": {
            "incident_id": incident_id,
            "zone_id": zone_id,
            "old_priority": old_priority,
            "new_priority": new_priority,
            "xai_string": xai_string,
            "disaster_type": disaster_type,
        },
        "timestamp": _now(),
        "source": "decision_engine",
    }
    await sio.emit("incident_priority_updated", payload, room="global_feed")
    await sio.emit("incident_priority_updated", payload, room=f"zone_{zone_id}")


async def emit_new_incident(incident: dict) -> None:
    """Fired when a new incident row is created (zone crosses threshold)."""
    payload = {
        "event": "new_incident",
        "payload": {
            "incident_id": incident.get("id"),
            "zone_id": incident.get("zone_id"),
            "lat": incident.get("lat"),
            "lng": incident.get("lng"),
            "disaster_type": incident.get("disaster_type"),
            "priority_score": incident.get("priority_score"),
        },
        "timestamp": _now(),
        "source": "decision_engine",
    }
    await sio.emit("new_incident", payload, room="global_feed")


async def emit_action_state_changed(action_id: str, zone_id: str, new_status: str,
                                     changed_by_role: str) -> None:
    """Fired after a commander approves or rejects an action."""
    payload = {
        "event": "action_state_changed",
        "payload": {
            "action_id": action_id,
            "zone_id": zone_id,
            "new_status": new_status,
            "changed_by_role": changed_by_role,
        },
        "timestamp": _now(),
        "source": "approval_gate",
    }
    await sio.emit("action_state_changed", payload, room="global_feed")
    await sio.emit("action_state_changed", payload, room=f"zone_{zone_id}")


async def emit_command_interaction(user_id: str, query: str, response: dict, source: str) -> None:
    """Fired when command center processes a user query."""
    payload = {
        "event": "command_interaction",
        "payload": {
            "user_id": user_id,
            "query": query,
            "response": response,
        },
        "timestamp": _now(),
        "source": source,
    }
    await sio.emit("command_interaction", payload, room="global_feed")


async def emit_prediction_updated(zone_id: str, disaster_type: str, result: dict) -> None:
    """Fired when prediction engine updates simulation results."""
    payload = {
        "event": "prediction_updated",
        "payload": {
            "zone_id": zone_id,
            "disaster_type": disaster_type,
            "result": result,
        },
        "timestamp": _now(),
        "source": "prediction_engine",
    }
    await sio.emit("prediction_updated", payload, room="global_feed")
    await sio.emit("prediction_updated", payload, room=f"zone_{zone_id}")


async def emit_resource_assigned(action_id: str, zone_id: str, resources: list) -> None:
    """Fired when resources are assigned to an incident."""
    payload = {
        "event": "resource_assigned",
        "payload": {
            "action_id": action_id,
            "zone_id": zone_id,
            "resources": resources,
        },
        "timestamp": _now(),
        "source": "resource_commander",
    }
    await sio.emit("resource_assigned", payload, room="global_feed")
    await sio.emit("resource_assigned", payload, room=f"zone_{zone_id}")


async def emit_route_changed(zone_id: str, route_data: dict) -> None:
    """Fired when routing information changes for a zone."""
    payload = {
        "event": "route_changed",
        "payload": {
            "zone_id": zone_id,
            "route_data": route_data,
        },
        "timestamp": _now(),
        "source": "route_intelligence",
    }
    await sio.emit("route_changed", payload, room="global_feed")
    await sio.emit("route_changed", payload, room=f"zone_{zone_id}")


async def emit_resource_status_updated(
    resource_id: str,
    zone_id: str | None,
    available: bool,
    current_load: int,
    capacity: int,
) -> None:
    """Fired when a resource availability/load changes."""
    payload = {
        "event": "resource_status_updated",
        "payload": {
            "resource_id": resource_id,
            "zone_id": zone_id,
            "available": available,
            "current_load": current_load,
            "capacity": capacity,
        },
        "timestamp": _now(),
        "source": "resource_commander",
    }
    await sio.emit("resource_status_updated", payload, room="global_feed")
    if zone_id:
        await sio.emit("resource_status_updated", payload, room=f"zone_{zone_id}")


async def emit_evidence_updated(zone_id: str, incident_id: str, bundle_summary: dict) -> None:
    """Fired when the Evidence Fusion service rebuilds an incident's bundle."""
    payload = {
        "event": "evidence_updated",
        "payload": {
            "incident_id": incident_id,
            "zone_id": zone_id,
            **bundle_summary,
        },
        "timestamp": _now(),
        "source": "evidence_fusion",
    }
    await sio.emit("evidence_updated", payload, room="global_feed")
    await sio.emit("evidence_updated", payload, room=f"zone_{zone_id}")


async def emit_weather_updated(
    zone_id: str,
    risk_score: float,
    previous_risk_score: float | None,
    data: dict,
) -> None:
    """Fired when a weather poll changes a zone's risk score (throttled —
    the poller only calls this on an actual change, §25)."""
    payload = {
        "event": "weather.updated",
        "payload": {
            "zone_id": zone_id,
            "risk_score": risk_score,
            "previous_risk_score": previous_risk_score,
            "rainfall_mm_hr": data.get("rainfall_mm_hr"),
            "wind_speed_kmh": data.get("wind_speed_kmh"),
            "weather_main": data.get("weather_main"),
            "weather_description": data.get("weather_description"),
        },
        "timestamp": _now(),
        "source": "weather_poller",
    }
    await sio.emit("weather.updated", payload, room="global_feed")
    await sio.emit("weather.updated", payload, room=f"zone_{zone_id}")


async def emit_earthquake_detected(events: list[dict]) -> None:
    """Fired once per poll when NEW seismic events are stored (never for
    already-known events)."""
    payload = {
        "event": "earthquake.detected",
        "payload": {
            "count": len(events),
            "events": events,
        },
        "timestamp": _now(),
        "source": "seismic_poller",
    }
    await sio.emit("earthquake.detected", payload, room="global_feed")
