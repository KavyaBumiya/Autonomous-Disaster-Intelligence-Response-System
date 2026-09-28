"""
BaseConnector — shared contract for every external provider (PRD §4).

Guarantees for all connectors:
    * async HTTP via httpx with a hard timeout
    * retry policy: exponential backoff with jitter (1s → 2s → 4s, capped 10s),
      honouring a provider Retry-After header when one is sent
      retryable = network errors, timeouts, HTTP 429, HTTP 5xx
      non-retryable = other HTTP 4xx (fail fast)
    * responses validated before returning; failures raised as ConnectorError
    * latency + provider status recorded in integrations.registry (§34)
    * secrets are never logged (only provider, path, status, latency)

Usage:
    class WeatherConnector(BaseConnector):
        provider = "open-meteo"
        base_url = settings.open_meteo_api_base

    resp = await connector.get_json("/forecast", params={...})
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx
import structlog

from app.integrations import registry

logger = structlog.get_logger()


class ConnectorError(Exception):
    """Normalized external-provider failure.

    Message is safe to log/return: it never carries credentials.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
        retry_after: float | None = None,
    ) -> None:
        self.provider = provider
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        # Seconds the provider asked us to wait (Retry-After), when it sent one.
        self.retry_after = retry_after
        super().__init__(f"{provider}: {message}")


def _parse_retry_after(headers: Any) -> float | None:
    """Read a Retry-After header into seconds.

    Supports both forms RFC 9110 allows: delta-seconds and an HTTP-date. Dates
    are resolved against wall-clock time; anything unparseable is ignored so a
    malformed header can never wedge the retry loop.
    """
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        when = parsedate_to_datetime(str(raw))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except (TypeError, ValueError, IndexError):
        return None


class BaseConnector:
    """Base class — subclasses override provider/base_url/timeouts."""

    provider: str = "base"
    base_url: str = ""
    timeout_seconds: float = 10.0
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 10.0

    # ── URL building ────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = self.base_url.rstrip("/")
        if not path:
            return base
        return f"{base}/{path.lstrip('/')}"

    # ── Core request with retry ─────────────────────────────────────────

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        content: bytes | str | None = None,
        expect_json: bool = False,
    ) -> httpx.Response:
        """Perform an HTTP request with retry/backoff. Returns a 2xx response
        or raises ConnectorError (final, after retries are exhausted).

        Circuit breaker (§31): when the registry says this provider is in an
        OFFLINE streak inside the cooldown window, no network call is made —
        ConnectorError is raised immediately so callers serve cache or report
        DEGRADED distinctly (never fabricate).

        expect_json=True validates the payload INSIDE the retry loop —
        providers sometimes answer 200 with an HTML page (rate-limit or
        maintenance notice), which is treated as a retryable failure."""
        url = self._url(path)
        started = time.perf_counter()
        delay = self.backoff_base_seconds
        error: ConnectorError | None = None

        if registry.circuit_open(self.provider):
            logger.warning(
                "connector_circuit_open",
                provider=self.provider,
                method=method,
                path=path,
                cooldown_s=registry.CIRCUIT_COOLDOWN_SECONDS,
            )
            raise ConnectorError(
                self.provider,
                "circuit open after repeated failures — live call skipped "
                "(serve cache or report DEGRADED; never fabricate)",
                retryable=True,
            )

        for attempt in range(1, self.max_attempts + 1):
            attempt_started = time.perf_counter()
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                ) as client:
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        json=json_body,
                        content=content,
                    )
                latency_ms = (time.perf_counter() - attempt_started) * 1000

                if resp.status_code == 429 or resp.status_code >= 500:
                    error = ConnectorError(
                        self.provider,
                        f"HTTP {resp.status_code}",
                        status_code=resp.status_code,
                        retryable=True,
                        retry_after=_parse_retry_after(resp.headers),
                    )
                elif resp.status_code >= 400:
                    error = ConnectorError(
                        self.provider,
                        f"HTTP {resp.status_code}",
                        status_code=resp.status_code,
                        retryable=False,
                    )
                elif expect_json:
                    try:
                        resp.json()
                    except ValueError:
                        # 2xx with HTML/empty body: rate-limit or maintenance
                        # page — transient, safe to retry.
                        error = ConnectorError(
                            self.provider,
                            "invalid JSON response (non-JSON 2xx body)",
                            status_code=resp.status_code,
                            retryable=True,
                        )
                    else:
                        total_ms = (time.perf_counter() - started) * 1000
                        registry.record_success(self.provider, total_ms)
                        logger.info(
                            "connector_ok",
                            provider=self.provider,
                            method=method,
                            path=path,
                            status=resp.status_code,
                            latency_ms=round(total_ms, 1),
                            attempt=attempt,
                        )
                        return resp
                else:
                    total_ms = (time.perf_counter() - started) * 1000
                    registry.record_success(self.provider, total_ms)
                    logger.info(
                        "connector_ok",
                        provider=self.provider,
                        method=method,
                        path=path,
                        status=resp.status_code,
                        latency_ms=round(total_ms, 1),
                        attempt=attempt,
                    )
                    return resp

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error = ConnectorError(
                    self.provider,
                    f"{type(exc).__name__}: {exc.__class__.__name__}",
                    retryable=True,
                )

            # Retry decision
            assert error is not None
            if not error.retryable or attempt >= self.max_attempts:
                break
            # Prefer the provider's own Retry-After over our schedule, but keep it
            # bounded so a hostile or mistaken header cannot stall the poller.
            wait = error.retry_after if error.retry_after is not None else delay
            wait = min(max(wait, 0.0), self.backoff_max_seconds)
            # Jitter spreads concurrent callers out instead of letting them retry
            # in lockstep. Without it, every zone's poller and every retryable API
            # request fires at the same instant, which is what turns a provider's
            # 429 into a self-sustaining retry storm.
            wait = wait * (0.5 + random.random() * 0.5)
            logger.warning(
                "connector_retry",
                provider=self.provider,
                method=method,
                path=path,
                attempt=attempt,
                error=error.message,
                next_delay_s=round(wait, 2),
                retry_after=error.retry_after,
            )
            await asyncio.sleep(wait)
            delay = min(delay * 2, self.backoff_max_seconds)

        total_ms = (time.perf_counter() - started) * 1000
        assert error is not None
        registry.record_failure(self.provider, error.message, latency_ms=total_ms)
        logger.warning(
            "connector_failed",
            provider=self.provider,
            method=method,
            path=path,
            error=error.message,
            status_code=error.status_code,
            latency_ms=round(total_ms, 1),
            attempts=attempt,
        )
        raise error

    # ── Convenience helpers ─────────────────────────────────────────────

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        content: bytes | str | None = None,
    ) -> httpx.Response:
        return await self.request(
            "POST", path, params=params, headers=headers, json_body=json_body, content=content
        )

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """GET and parse JSON; invalid payloads are retried, then raised
        as ConnectorError."""
        resp = await self.request(
            "GET", path, params=params, headers=headers, expect_json=True
        )
        try:
            return resp.json()
        except ValueError as exc:  # pragma: no cover — request() pre-validates
            raise ConnectorError(
                self.provider,
                f"invalid JSON response: {type(exc).__name__}",
                status_code=resp.status_code,
                retryable=False,
            ) from exc

    # ── Health (§31) ────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Provider status from the shared registry — no live probe."""
        return {"provider": self.provider, **registry.snapshot().get(self.provider, {"status": "UNKNOWN"})}
