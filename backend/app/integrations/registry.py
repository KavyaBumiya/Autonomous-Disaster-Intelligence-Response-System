"""
Provider status registry — observable health of every external connector (§31/§34).

Every BaseConnector call reports success/failure here. The snapshot() output
is surfaced by GET /api/health as an additive `providers` block so the
frontend can show per-source DEGRADED/OFFLINE states without extra probes.

State machine:
    UNKNOWN  — never called yet
    ONLINE   — last call succeeded
    DEGRADED — 1–2 consecutive failures after a prior success
    OFFLINE  — 3+ consecutive failures, or a failure with no prior success

Thread-safety: module-level lock (registry is read/written from poller
tasks, request handlers, and background pipelines interchangeably).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

DEGRADED_AFTER_FAILURES = 1
OFFLINE_AFTER_FAILURES = 3

# Circuit breaker (§31): once a provider hits OFFLINE streaks, live calls are
# skipped for this long (callers serve cache / fall back honestly). After the
# cooldown the circuit goes half-open and the next call probes the provider.
CIRCUIT_COOLDOWN_SECONDS = 60.0

# Canonical provider groups surfaced by /api/health (plan Phase 16, §31).
# Worst-status wins when a group has multiple sources.
CANONICAL_GROUPS: dict[str, tuple[str, ...]] = {
    "weather": ("open-meteo",),
    "seismic": ("usgs",),
    "gis": ("osm/overpass",),
    "routing": ("osrm",),
    "geocoding": ("nominatim",),
    "groq": ("groq",),
    "natural_events": ("nasa/eonet",),
}

_STATUS_RANK = {"ONLINE": 0, "UNKNOWN": 1, "DEGRADED": 2, "OFFLINE": 3}


@dataclass
class ProviderState:
    status: str = "UNKNOWN"            # UNKNOWN | ONLINE | DEGRADED | OFFLINE
    total_calls: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_success_at: float | None = None   # unix seconds
    last_failure_at: float | None = None
    last_error: str | None = None
    last_latency_ms: float | None = None
    latency_ms_ewma: float | None = None   # exponentially weighted moving average
    # Extra provider-specific detail (model, feed, etc.) — never secrets.
    detail: dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_providers: dict[str, ProviderState] = {}

_EWMA_ALPHA = 0.3


def _state(provider: str) -> ProviderState:
    st = _providers.get(provider)
    if st is None:
        st = ProviderState()
        _providers[provider] = st
    return st


def record_success(provider: str, latency_ms: float, *, detail: dict[str, Any] | None = None) -> None:
    """Mark a successful provider call; resets failure streak."""
    with _lock:
        st = _state(provider)
        st.total_calls += 1
        st.consecutive_failures = 0
        st.status = "ONLINE"
        st.last_success_at = time.time()
        st.last_error = None
        st.last_latency_ms = round(latency_ms, 1)
        if st.latency_ms_ewma is None:
            st.latency_ms_ewma = st.last_latency_ms
        else:
            st.latency_ms_ewma = round(
                _EWMA_ALPHA * st.last_latency_ms + (1 - _EWMA_ALPHA) * st.latency_ms_ewma, 1
            )
        if detail:
            st.detail.update(detail)


def record_failure(provider: str, error: str, *, latency_ms: float | None = None) -> None:
    """Mark a failed provider call; advances DEGRADED → OFFLINE by streak."""
    with _lock:
        st = _state(provider)
        st.total_calls += 1
        st.total_failures += 1
        st.consecutive_failures += 1
        st.last_failure_at = time.time()
        st.last_error = error[:300]
        if latency_ms is not None:
            st.last_latency_ms = round(latency_ms, 1)
        if st.consecutive_failures >= OFFLINE_AFTER_FAILURES or st.last_success_at is None:
            st.status = "OFFLINE"
        elif st.consecutive_failures >= DEGRADED_AFTER_FAILURES:
            st.status = "DEGRADED"


def get_status(provider: str) -> str:
    with _lock:
        st = _providers.get(provider)
        return st.status if st else "UNKNOWN"


def _circuit_open_locked(st: ProviderState) -> bool:
    """Circuit-open predicate (caller holds _lock).

    Open only after a real OFFLINE streak (>= OFFLINE_AFTER_FAILURES
    consecutive failures) AND only inside the cooldown window. Past the
    cooldown the circuit is half-open: one probe call is allowed through;
    success closes it, failure re-arms the cooldown via record_failure.
    """
    if st.consecutive_failures < OFFLINE_AFTER_FAILURES:
        return False
    last = st.last_failure_at or 0.0
    return (time.time() - last) < CIRCUIT_COOLDOWN_SECONDS


def circuit_open(provider: str) -> bool:
    """True when live calls to the provider should be skipped (§31).

    Callers raise ConnectorError immediately without touching the network;
    they then serve cache or report DEGRADED distinctly — never fabricate.
    """
    with _lock:
        st = _providers.get(provider)
        if st is None:
            return False
        return _circuit_open_locked(st)


def canonical_statuses(snap: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
    """Canonical provider group statuses for /api/health (plan Phase 16).

    Keys: weather, seismic, gis, routing, geocoding, groq →
    ONLINE | DEGRADED | OFFLINE | UNKNOWN (never-probed groups stay UNKNOWN).
    """
    data = snap if snap is not None else snapshot()
    out: dict[str, str] = {}
    for group, names in CANONICAL_GROUPS.items():
        statuses = [data.get(n, {}).get("status", "UNKNOWN") for n in names]
        out[group] = max(statuses, key=lambda s: _STATUS_RANK.get(s, 1))
    return out


def snapshot() -> dict[str, dict[str, Any]]:
    """Provider statuses for health endpoints — JSON-safe, never secrets."""
    with _lock:
        out: dict[str, dict[str, Any]] = {}
        for name, st in _providers.items():
            out[name] = {
                "status": st.status,
                "last_success_at": st.last_success_at,
                "last_error": st.last_error,
                "consecutive_failures": st.consecutive_failures,
                "latency_ms": st.latency_ms_ewma,
                "total_calls": st.total_calls,
                "total_failures": st.total_failures,
                "circuit": "open" if _circuit_open_locked(st) else "closed",
                **({"detail": dict(st.detail)} if st.detail else {}),
            }
        return out


def reset() -> None:
    """Clear all state (tests only)."""
    with _lock:
        _providers.clear()
