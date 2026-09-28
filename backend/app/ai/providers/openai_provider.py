"""
OpenAIProvider — OpenAI API connector as an AIModelProvider.

Wraps the existing OpenAIConnector into the provider abstraction.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.ai.providers.base import (
    AIModelProvider,
    ModelInfo,
    PredictionResult,
    TaskType,
)
from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class OpenAIProvider(AIModelProvider):
    """OpenAI API provider."""

    provider_name = "openai"
    supported_tasks = [
        TaskType.TEXT_GENERATION,
        TaskType.TEXT_SUMMARIZATION,
        TaskType.TRANSLATION,
        TaskType.EXPLAINABILITY,
        TaskType.REPORT_PARSING,
    ]

    def __init__(self) -> None:
        self._connector = None

    def _get_connector(self):
        if self._connector is None:
            from app.integrations.ai.openai_service import OpenAIConnector
            self._connector = OpenAIConnector()
        return self._connector

    async def health(self) -> dict[str, Any]:
        try:
            connector = self._get_connector()
            if not connector.configured:
                return {
                    "provider": self.provider_name,
                    "status": "OFFLINE",
                    "reason": "OPENAI_API_KEY not configured",
                }
            return {
                "provider": self.provider_name,
                "status": "ONLINE",
            }
        except Exception as exc:
            return {
                "provider": self.provider_name,
                "status": "OFFLINE",
                "reason": str(exc),
            }

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                model_id="openai-gpt-4o-mini",
                model_name="gpt-4o-mini",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.TEXT_GENERATION,
                input_schema={"messages": "array[object]"},
                output_schema={"content": "string"},
                status="staging",
            ),
        ]

    async def predict(
        self,
        task: TaskType,
        input_data: Any,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> PredictionResult:
        started = time.perf_counter()
        now = datetime.now(timezone.utc).isoformat()

        try:
            connector = self._get_connector()
            model = model_id or "gpt-4o-mini"

            messages = input_data if isinstance(input_data, list) else [
                {"role": "user", "content": str(input_data)},
            ]

            result = await connector.chat_completion(
                messages,
                model=model,
                temperature=kwargs.get("temperature", 0.0),
                max_tokens=kwargs.get("max_tokens", 1024),
            )

            return PredictionResult(
                prediction=result.content,
                confidence=0.8,
                model_id=model,
                model_version="1.0.0",
                provider=self.provider_name,
                task=task,
                generated_at=now,
                explanation="Generated via OpenAI API",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        except Exception as exc:
            logger.warning("openai_predict_failed", task=task.value, error=str(exc))
            return PredictionResult(
                prediction=None,
                confidence=0.0,
                model_id=model_id or "gpt-4o-mini",
                model_version="0.0.0",
                provider=self.provider_name,
                task=task,
                generated_at=now,
                explanation=f"Prediction unavailable: {exc}",
                uncertainty="OpenAI API inference failed",
                limitations=[str(exc)],
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback_used=True,
                fallback_reason=str(exc),
            )


_openai_provider: OpenAIProvider | None = None


def get_openai_provider() -> OpenAIProvider:
    global _openai_provider
    if _openai_provider is None:
        _openai_provider = OpenAIProvider()
    return _openai_provider
