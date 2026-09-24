"""
AEGIS-AI — Command Center conversation store
=============================================
Short multi-turn history for the commander chat, kept in Redis (PRD §11).

- Key:  aegis:cmd:conv:{conversation_id}
- TTL:  30 minutes idle (avoids unbounded growth)
- Caps: last N exchanges, each message truncated

Falls back to an in-process dict when Redis is unreachable so the chat still
works in DEGRADED MODE (PRD §22).
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

MAX_TURNS = 12          # pairs of user+assistant messages retained
MAX_CHARS = 2000        # per message content
TTL_SECONDS = 30 * 60   # 30 minutes

_client: aioredis.Redis | None = None
_memory: dict[str, list[dict]] = {}


async def _redis() -> aioredis.Redis | None:
    global _client
    if _client is None:
        try:
            _client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception as exc:
            logger.warning("conversation_redis_unavailable", error=str(exc))
            return None
    return _client


def _key(conversation_id: str) -> str:
    return f"aegis:cmd:conv:{conversation_id}"


def _truncate(content: str) -> str:
    text = content or ""
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + "…"
    return text


async def load_history(conversation_id: str) -> list[dict]:
    """Return prior messages as OpenAI-style [{role, content}, ...]."""
    if not conversation_id:
        return []

    r = await _redis()
    if r is not None:
        try:
            raw = await r.get(_key(conversation_id))
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    return data
        except Exception as exc:
            logger.warning("conversation_load_failed", error=str(exc))

    return _memory.get(conversation_id, [])


async def append_turn(
    conversation_id: str,
    user_query: str,
    assistant_response: str,
) -> None:
    """Append one exchange, trim to MAX_TURNS, refresh TTL."""
    if not conversation_id:
        return

    entry = [
        {"role": "user", "content": _truncate(user_query)},
        {"role": "assistant", "content": _truncate(assistant_response)},
    ]

    # Memory fallback path
    history = _memory.get(conversation_id)
    if history is None:
        history = await load_history(conversation_id)

    history = (history or []) + entry
    # Keep only the last MAX_TURNS exchanges (2 messages each)
    if len(history) > MAX_TURNS * 2:
        history = history[-(MAX_TURNS * 2):]
    _memory[conversation_id] = history

    r = await _redis()
    if r is not None:
        try:
            await r.set(
                _key(conversation_id),
                json.dumps(history),
                ex=TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("conversation_save_failed", error=str(exc))


async def clear_history(conversation_id: str) -> None:
    if not conversation_id:
        return
    _memory.pop(conversation_id, None)
    r = await _redis()
    if r is not None:
        try:
            await r.delete(_key(conversation_id))
        except Exception:
            pass
