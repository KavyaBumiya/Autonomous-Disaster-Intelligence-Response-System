"""
Flood IoT Simulation endpoints.

Accepts water_level, flow_velocity, and timestamp from IoT sensors,
validates them, and broadcasts the reading to all connected Socket.IO clients.
"""
from datetime import datetime
from fastapi import APIRouter

from app.services.websocket import sio

router = APIRouter()


@router.post("/data")
async def receive_flood_data(payload: dict):
    """Receive a flood sensor reading and broadcast it via Socket.IO."""
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

    await sio.emit("flood_reading", reading)

    return {"status": "ok", "reading": reading}
