"""
LocalModelProvider — locally-hosted models (whisper, distilbert, etc.).

These models run in-process via transformers/torch. They are loaded
lazily and cached. The provider never raises — failures return fallback
PredictionResults with explicit uncertainty.
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


class LocalModelProvider(AIModelProvider):
    """Local in-process model provider."""

    provider_name = "local"
    supported_tasks = [
        TaskType.SPEECH_TO_TEXT,
        TaskType.TEXT_CLASSIFICATION,
        TaskType.HAZARD_CLASSIFICATION,
        TaskType.NAMED_ENTITY_RECOGNITION,
    ]

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._pipelines: dict[str, Any] = {}

    async def health(self) -> dict[str, Any]:
        try:
            import torch
            return {
                "provider": self.provider_name,
                "status": "ONLINE",
                "torch_version": torch.__version__,
                "cuda_available": torch.cuda.is_available(),
            }
        except ImportError:
            return {
                "provider": self.provider_name,
                "status": "OFFLINE",
                "reason": "torch not installed",
            }

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                model_id="local-whisper-base",
                model_name="openai/whisper-base",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.SPEECH_TO_TEXT,
                input_schema={"audio_path": "string"},
                output_schema={"transcript": "string", "language": "string"},
                resource_requirements={"memory_mb": 500, "cpu_cores": 2},
                status="staging",
            ),
            ModelInfo(
                model_id="local-distilbert-classifier",
                model_name="distilbert-base-uncased-finetuned-sst-2-english",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.TEXT_CLASSIFICATION,
                input_schema={"text": "string"},
                output_schema={"label": "string", "confidence": "float"},
                resource_requirements={"memory_mb": 300, "cpu_cores": 1},
                status="staging",
            ),
            ModelInfo(
                model_id="local-spacy-ner",
                model_name="en_core_web_sm",
                provider=self.provider_name,
                version="3.7.4",
                task=TaskType.NAMED_ENTITY_RECOGNITION,
                input_schema={"text": "string"},
                output_schema={"entities": "array"},
                resource_requirements={"memory_mb": 100, "cpu_cores": 1},
                status="production",
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
            if task == TaskType.SPEECH_TO_TEXT:
                return await self._speech_to_text(input_data, model_id, now, started)
            elif task == TaskType.TEXT_CLASSIFICATION:
                return await self._text_classification(input_data, model_id, now, started)
            elif task == TaskType.NAMED_ENTITY_RECOGNITION:
                return await self._ner(input_data, model_id, now, started)
            else:
                return self._fallback_result(task, model_id or "unknown", now, started, f"Task {task.value} not supported locally")
        except Exception as exc:
            logger.warning("local_predict_failed", task=task.value, error=str(exc))
            return self._fallback_result(task, model_id or "unknown", now, started, str(exc))

    async def _speech_to_text(self, input_data: Any, model_id: str | None, now: str, started: float) -> PredictionResult:
        audio_path = input_data if isinstance(input_data, str) else input_data.get("audio_path", "")
        model_name = model_id or "local-whisper-base"

        from transformers import pipeline
        pipe = self._get_pipeline("automatic-speech-recognition", model_name)
        output = pipe(audio_path)

        return PredictionResult(
            prediction=output.get("text", ""),
            confidence=0.85,
            model_id=model_name,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.SPEECH_TO_TEXT,
            generated_at=now,
            explanation="Transcribed via local Whisper model",
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def _text_classification(self, input_data: Any, model_id: str | None, now: str, started: float) -> PredictionResult:
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")
        model_name = model_id or "local-distilbert-classifier"

        from transformers import pipeline
        pipe = self._get_pipeline("text-classification", model_name)
        output = pipe(text, truncation=True)

        return PredictionResult(
            prediction=output[0]["label"] if output else "unknown",
            confidence=output[0]["score"] if output else 0.0,
            model_id=model_name,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.TEXT_CLASSIFICATION,
            generated_at=now,
            explanation=f"Classified as {output[0]['label']}" if output else "No prediction",
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def _ner(self, input_data: Any, model_id: str | None, now: str, started: float) -> PredictionResult:
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")

        try:
            import spacy
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(text[:512])
            entities = [{"entity": ent.label_, "text": ent.text} for ent in doc.ents]
        except ImportError:
            entities = []

        return PredictionResult(
            prediction=entities,
            confidence=0.8 if entities else 0.0,
            model_id="local-spacy-ner",
            model_version="3.7.4",
            provider=self.provider_name,
            task=TaskType.NAMED_ENTITY_RECOGNITION,
            generated_at=now,
            explanation=f"Extracted {len(entities)} entities via spaCy",
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _get_pipeline(self, task: str, model_id: str):
        cache_key = f"{task}:{model_id}"
        if cache_key not in self._pipelines:
            from transformers import pipeline
            self._pipelines[cache_key] = pipeline(task, model=model_id)
        return self._pipelines[cache_key]

    def _fallback_result(self, task: TaskType, model_id: str, now: str, started: float, reason: str) -> PredictionResult:
        return PredictionResult(
            prediction=None,
            confidence=0.0,
            model_id=model_id,
            model_version="0.0.0",
            provider=self.provider_name,
            task=task,
            generated_at=now,
            explanation=f"Prediction unavailable: {reason}",
            uncertainty="Local model inference failed",
            limitations=[reason],
            latency_ms=(time.perf_counter() - started) * 1000,
            fallback_used=True,
            fallback_reason=reason,
        )


_local_provider: LocalModelProvider | None = None


def get_local_provider() -> LocalModelProvider:
    global _local_provider
    if _local_provider is None:
        _local_provider = LocalModelProvider()
    return _local_provider
