"""
Device authentication for the IoT telemetry API.

Devices authenticate with a per-device bearer token issued at registration.
The token is stored as a SHA-256 hash — never in plaintext, never logged, and
never returned after the registration response.

The registration endpoint itself is gated by a shared bootstrap secret
(IOT_REGISTRATION_TOKEN) so that not anyone can create devices. That secret
only gates registration; it is never accepted on the telemetry endpoint.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.device import FloodDevice


def hash_device_token(token: str) -> str:
    """SHA-256 of a device token. Tokens are high-entropy random strings, so a
    plain hash is sufficient — no salt needed because the input is not a
    low-entropy password."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_device_token() -> str:
    """Cryptographically random device token (48 hex chars = 192 bits)."""
    return secrets.token_hex(24)


def verify_device_token(plain: str, token_hash: str) -> bool:
    """Constant-time comparison of a presented token against its stored hash."""
    return hmac.compare_digest(hash_device_token(plain), token_hash)


def extract_bearer_token(request: Request) -> Optional[str]:
    """Pull the token out of `Authorization: Bearer <token>`. Returns None when
    the header is absent or malformed."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def get_current_device(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FloodDevice:
    """Resolve the authenticated device or raise 401/403.

    401 — no token presented (the device has not registered yet).
    403 — a token was presented but does not match any registered device.
    """
    settings = get_settings()
    token = extract_bearer_token(request)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing device token. Register the device first: "
                   "POST /api/iot/v1/devices/register",
        )

    # Dev-only escape hatch so local integration tests can run without
    # registering a device. Never enabled in production.
    trusted = {
        d.strip() for d in settings.iot_trusted_device_ids.split(",") if d.strip()
    }
    if settings.is_development and token in trusted:
        device = (
            await db.execute(
                select(FloodDevice).where(FloodDevice.device_id == token).limit(1)
            )
        ).scalar_one_or_none()
        if device is not None:
            return device

    token_hash = hash_device_token(token)
    device = (
        await db.execute(
            select(FloodDevice).where(FloodDevice.token_hash == token_hash).limit(1)
        )
    ).scalar_one_or_none()

    if device is None:
        raise HTTPException(status_code=403, detail="Invalid device token")
    if device.status != "active":
        raise HTTPException(status_code=403, detail=f"Device is {device.status}")

    return device
