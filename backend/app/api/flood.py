"""
Flood IoT Simulation endpoints.

POST /data accepts water_level, flow_velocity, and timestamp from IoT sensors,
validates them, and broadcasts the reading to all connected Socket.IO clients.

GET /data returns the most recent reading so the console can show the latest
sensor value even when it loaded after the broadcast. There is no
`flood_readings` table: readings are transient by design, so the last one is
held in process state and reported as `no_data` until a sensor posts.
"""
from datetime import datetime, timezone
from fastapi import APIRouter

from app.services.websocket import sio

router = APIRouter()

# Last ingested reading, held in process state. Readings are transient (there is
# no flood_readings table), so this is the only record of a sensor value once
# the broadcast has been delivered. Single event-loop, so plain assignment is
# safe.
_last_reading: dict | None = None
_last_received_at: datetime | None = None


@router.get("/data")
async def get_flood_data():
    """Latest flood sensor reading, or an explicit no-data state.

    A 200 with `status: "no_data"` rather than a 404: the console polls this
    every 5 s, and a 404 would be indistinguishable from a broken endpoint.
    The distinction that matters is "no sensor has reported yet", which is a
    real state, not an error.
    """
    if _last_reading is None:
        return {"status": "no_data", "reading": None,
                "detail": "no flood sensor has reported yet"}

    age_seconds = None
    if _last_received_at is not None:
        age_seconds = round(
            max(0.0, (datetime.now(timezone.utc) - _last_received_at).total_seconds()), 1
        )

    return {
        "status": "ok",
        "reading": _last_reading,
        "received_at": _last_received_at.isoformat() if _last_received_at else None,
        "age_seconds": age_seconds,
    }


@router.post("/data")
async def receive_flood_data(payload: dict):
    """Receive a flood sensor reading and broadcast it via Socket.IO."""
    global _last_reading, _last_received_at

    try:
        water_level = float(payload["water_level"])
    except (KeyError, TypeError, ValueError):
        return {"status": "error", "detail": "water_level must be numeric"}

    try:
        flow_velocity = float(payload["flow_velocity"])
    except (KeyError, TypeError, ValueError):
        return {"status": "error", "detail": "flow_velocity must be numeric"}

    timestamp_str = payload.get("timestamp", "")
    try:
        datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return {"status": "error", "detail": "timestamp must be a valid ISO 8601 string"}

    reading = {
        "water_level": water_level,
        "flow_velocity": flow_velocity,
        "timestamp": timestamp_str,
    }

    _last_reading = reading
    _last_received_at = datetime.now(timezone.utc)

    await sio.emit("flood_reading", reading)

    return {"status": "ok", "reading": reading}
