"""
AEGIS-AI — NVIDIA NIM AI connector
==================================
Minimal async client for NVIDIA's OpenAI-compatible chat-completions API.

    base URL : https://integrate.api.nvidia.com/v1
    auth     : Authorization: Bearer $NVIDIA_API_KEY
    endpoint : POST /chat/completions
    models   : OpenAI-style namespaced ids, e.g.
               "deepseek-ai/deepseek-v4.1-flash"

Replaces the previous Groq SDK transport. The wire format is identical
(chat/completions + `tools`), so the AI Gateway layer above is unchanged apart
from the provider name.

Reuses BaseConnector so the AI provider gets the same guarantees as every other
external dependency: async httpx with a hard timeout, exponential backoff on
429/5xx/network errors, fail-fast on other 4xx, a circuit breaker once it hits
an OFFLINE streak, and a status entry in integrations.registry (§31/§34).

SECURITY (PRD §3): the API key is read from server-side settings only. It is
never logged and never returned in an API response — errors carry the HTTP
status and a truncated provider message, nothing more.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError

logger = structlog.get_logger()

# Providers that answer "Return ONLY JSON" with a fenced block.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


@dataclass
class NvidiaToolCall:
    """One tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = "{}"


@dataclass
class NvidiaChatResult:
    """Normalised chat-completion result (provider-agnostic for callers)."""

    content: str
    model: str
    tool_calls: list[NvidiaToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def usage_total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def extract_json(content: str) -> str:
    """Best-effort extraction of a JSON object from model output.

    DeepSeek-style models occasionally wrap JSON in a ```json fence or add a
    one-line preamble. Pydantic validation is still the final gate, so this only
    removes noise instead of trusting anything.
    """
    text = (content or "").strip()
    if not text:
        return text

    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    if text.startswith(("{", "[")):
        return text

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            return text[start : end + 1]

    return text


class NvidiaNIMConnector(BaseConnector):
    """NVIDIA NIM chat-completions connector (OpenAI-compatible)."""

    provider = "nvidia"
    max_attempts = 3

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.nvidia_api_key
        self.base_url = settings.nvidia_base_url
        self.timeout_seconds = settings.nvidia_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ConnectorError(
                self.provider,
                "NVIDIA_API_KEY is not set — add it to the server-side .env. "
                "Never expose this key to the browser.",
                retryable=False,
            )
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Chat completions ────────────────────────────────────────────────

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        json_mode: bool = False,
    ) -> NvidiaChatResult:
        """POST /chat/completions and normalise the response.

        json_mode asks for a JSON object; models that reject response_format
        are retried once without it, so parsing degrades to "extract JSON from
        prose" instead of failing the call.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            payload = await self._post_chat(body)
        except ConnectorError as exc:
            # NIM models without JSON-mode support answer 400; retry once
            # without response_format rather than failing the whole task.
            if json_mode and exc.status_code == 400:
                logger.info("nvidia_json_mode_unsupported", model=model)
                body.pop("response_format", None)
                payload = await self._post_chat(body)
            else:
                raise

        return self._parse(payload, requested_model=model)

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        resp = await self.request(
            "POST",
            "/chat/completions",
            headers=self._headers(),
            json_body=body,
            expect_json=True,
        )
        data = resp.json()
        if not isinstance(data, dict):
            raise ConnectorError(self.provider, "unexpected response shape")
        return data

    def _parse(self, data: dict[str, Any], *, requested_model: str) -> NvidiaChatResult:
        choices = data.get("choices") or []
        if not choices:
            raise ConnectorError(
                self.provider,
                f"response contained no choices (model={requested_model})",
            )

        choice = choices[0] or {}
        message = choice.get("message") or {}
        usage = data.get("usage") or {}

        return NvidiaChatResult(
            content=message.get("content") or "",
            model=data.get("model") or requested_model,
            tool_calls=[
                NvidiaToolCall(
                    id=tc.get("id") or "",
                    name=(tc.get("function") or {}).get("name") or "",
                    arguments=_safe_args((tc.get("function") or {}).get("arguments")),
                    raw_arguments=(tc.get("function") or {}).get("arguments") or "{}",
                )
                for tc in (message.get("tool_calls") or [])
            ],
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )

    # ── Discovery ───────────────────────────────────────────────────────

    async def list_models(self) -> list[str]:
        """Model ids published by the NIM catalog.

        NOTE: GET /v1/models is a public endpoint - it answers 200 even with
        no key at all, so a successful call here does NOT prove the key is
        valid. Use health() to verify credentials.
        """
        try:
            data = await self.get_json("/models", headers=self._headers())
        except ConnectorError as exc:
            logger.warning("nvidia_model_list_failed", error=exc.message)
            return []
        entries = data.get("data") or []
        return [m.get("id") for m in entries if isinstance(m, dict) and m.get("id")]

    async def health(self) -> dict[str, Any]:
        """Live probe: does this key actually authenticate against NIM?

        A minimal chat completion is used deliberately: GET /v1/models is
        public and returns 200 for any caller (even unauthenticated), so it
        cannot distinguish a valid key from a revoked or wrong one.
        """
        if not self.configured:
            return {
                "provider": self.provider,
                "status": "OFFLINE",
                "reason": "NVIDIA_API_KEY is not configured",
            }
        try:
            await self.chat_completion(
                [{"role": "user", "content": "ping"}],
                model=self._probe_model(),
                max_tokens=1,
            )
        except ConnectorError as exc:
            return {
                "provider": self.provider,
                "status": "OFFLINE",
                "reason": exc.message,
                "status_code": exc.status_code,
            }
        return {
            "provider": self.provider,
            "status": "ONLINE",
            "status_code": 200,
        }

    def _probe_model(self) -> str:
        return get_settings().nvidia_model


def _safe_args(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON *string*; malformed → {}."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("nvidia_tool_args_unparseable")
        return {}
    return parsed if isinstance(parsed, dict) else {}


_client: NvidiaNIMConnector | None = None


def get_nvidia_client() -> NvidiaNIMConnector:
    """Process-wide connector singleton (stateless + safe to share)."""
    global _client
    if _client is None:
        _client = NvidiaNIMConnector()
    return _client
