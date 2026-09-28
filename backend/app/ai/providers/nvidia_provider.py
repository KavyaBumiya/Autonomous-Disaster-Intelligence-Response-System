"""
NvidiaProvider — wraps the existing NVIDIA NIM connector as an AIModelProvider.

This bridges the existing ai_gateway.py (NVIDIA NIM chat completions) into
the new provider abstraction, so the model router can treat it uniformly.
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


class NvidiaProvider(AIModelProvider):
    """NVIDIA NIM provider — wraps existing NvidiaNIMConnector."""

    provider_name = "nvidia"
    supported_tasks = [
        TaskType.TEXT_GENERATION,
        TaskType.TEXT_SUMMARIZATION,
        TaskType.TRANSLATION,
        TaskType.EXPLAINABILITY,
        TaskType.REPORT_PARSING,
        TaskType.HAZARD_CLASSIFICATION,
    ]

    def __init__(self) -> None:
        self._connector = None

    def _get_connector(self):
        if self._connector is None:
            from app.integrations.ai.nvidia_service import get_nvidia_client
            self._connector = get_nvidia_client()
        return self._connector

    async def health(self) -> dict[str, Any]:
        try:
            connector = self._get_connector()
            return await connector.health()
        except Exception as exc:
            return {
                "provider": self.provider_name,
                "status": "OFFLINE",
                "reason": str(exc),
            }

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                model_id="nvidia-deepseek-v4-flash",
                model_name=settings.nvidia_model,
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.TEXT_GENERATION,
                input_schema={"messages": "array[object]"},
                output_schema={"content": "string"},
                resource_requirements={"api": "nvidia-nim"},
                status="production",
            ),
            ModelInfo(
                model_id="nvidia-fallback",
                model_name=settings.nvidia_fallback_model or "none",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.TEXT_GENERATION,
                input_schema={"messages": "array[object]"},
                output_schema={"content": "string"},
                resource_requirements={"api": "nvidia-nim"},
                status="experimental",
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
            model = model_id or settings.nvidia_model

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
                explanation="Generated via NVIDIA NIM",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        except Exception as exc:
            logger.warning("nvidia_predict_failed", task=task.value, error=str(exc))
            return PredictionResult(
                prediction=None,
                confidence=0.0,
                model_id=model_id or settings.nvidia_model,
                model_version="0.0.0",
                provider=self.provider_name,
                task=task,
                generated_at=now,
                explanation=f"Prediction unavailable: {exc}",
                uncertainty="NVIDIA NIM inference failed",
                limitations=[str(exc)],
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback_used=True,
                fallback_reason=str(exc),
            )


_nvidia_provider: NvidiaProvider | None = None


def get_nvidia_provider() -> NvidiaProvider:
    global _nvidia_provider
    if _nvidia_provider is None:
        _nvidia_provider = NvidiaProvider()
    return _nvidia_provider
