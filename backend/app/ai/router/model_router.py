"""
Model Router — intelligent model selection based on:
    - hazard type
    - location/resolution
    - data availability
    - latency requirements
    - hardware availability

The router never calls every model for every request.
It uses task-specific routing to select the best provider+model.
"""
from __future__ import annotations

import structlog
from typing import Any

from app.ai.providers.base import AIModelProvider, PredictionResult, TaskType
from app.ai.registry.model_registry import get_model_registry

logger = structlog.get_logger()


class ModelRouter:
    """Routes inference requests to the best model/provider."""

    def __init__(self) -> None:
        self._providers: dict[str, AIModelProvider] = {}

    def register_provider(self, provider: AIModelProvider) -> None:
        self._providers[provider.provider_name] = provider
        logger.info("provider_registered", provider=provider.provider_name)

    async def route(
        self,
        task: TaskType,
        input_data: Any,
        *,
        hazard: str | None = None,
        resolution: str | None = None,
        data_available: dict[str, bool] | None = None,
        latency_requirement: str = "normal",  # low | normal | high
        hardware: str = "cpu",  # cpu | gpu | any
        preferred_provider: str | None = None,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> PredictionResult:
        """Select and call the best model for the task.

        Routing logic:
        1. If model_id specified, use that exact model
        2. If preferred_provider specified, try that provider first
        3. Otherwise, select based on task + hazard + latency
        4. Fallback chain: primary → secondary → rules baseline
        """
        registry = get_model_registry()

        # 1. Direct model selection
        if model_id:
            entry = registry.get(model_id)
            if entry:
                provider = self._providers.get(entry.info.provider)
                if provider:
                    result = await provider.predict(task, input_data, model_id=model_id, **kwargs)
                    registry.record_usage(model_id, result.latency_ms, not result.fallback_used)
                    return result

        # 2. Preferred provider
        if preferred_provider and preferred_provider in self._providers:
            provider = self._providers[preferred_provider]
            if provider.supports(task):
                result = await provider.predict(task, input_data, **kwargs)
                registry.record_usage(result.model_id, result.latency_ms, not result.fallback_used)
                return result

        # 3. Task-based routing
        candidates = self._select_candidates(task, hazard, resolution, latency_requirement, hardware)

        for provider_name, model_id_candidate in candidates:
            provider = self._providers.get(provider_name)
            if provider and provider.supports(task):
                try:
                    result = await provider.predict(task, input_data, model_id=model_id_candidate, **kwargs)
                    if not result.fallback_used:
                        registry.record_usage(result.model_id, result.latency_ms, True)
                        return result
                except Exception as exc:
                    logger.warning("router_provider_failed", provider=provider_name, error=str(exc))
                    continue

        # 4. Fallback: return unavailable
        logger.warning("router_no_model_available", task=task.value, hazard=hazard)
        return PredictionResult(
            prediction=None,
            confidence=0.0,
            model_id="none",
            model_version="0.0.0",
            provider="none",
            task=task,
            generated_at="",
            explanation="No model available for this task",
            uncertainty="All models failed or none registered",
            limitations=["No suitable model found"],
            fallback_used=True,
            fallback_reason="No model available",
        )

    def _select_candidates(
        self,
        task: TaskType,
        hazard: str | None,
        resolution: str | None,
        latency_requirement: str,
        hardware: str,
    ) -> list[tuple[str, str | None]]:
        """Select candidate (provider, model_id) pairs in priority order."""
        candidates: list[tuple[str, str | None]] = []

        # Hazard-specific routing
        if hazard in ("flood", "flash_flood", "river_flood", "coastal_flood"):
            if task == TaskType.HAZARD_CLASSIFICATION:
                candidates.extend([
                    ("huggingface", "aegis-hazard-classifier-v1"),
                    ("local", "local-distilbert-classifier"),
                    ("nvidia", None),
                ])
            elif task == TaskType.FLOOD_MAPPING:
                candidates.extend([
                    ("huggingface", "aegis-flood-mapping-v1"),
                    ("local", None),
                ])
        elif hazard in ("wildfire", "fire"):
            if task == TaskType.WILDFIRE_DETECTION:
                candidates.extend([
                    ("huggingface", "aegis-wildfire-detection-v1"),
                    ("local", None),
                ])
            elif task == TaskType.DAMAGE_ASSESSMENT:
                candidates.extend([
                    ("huggingface", "aegis-damage-assessment-v1"),
                    ("local", None),
                ])
        elif hazard in ("earthquake", "tsunami"):
            if task == TaskType.HAZARD_CLASSIFICATION:
                candidates.extend([
                    ("huggingface", "aegis-hazard-classifier-v1"),
                    ("local", "local-distilbert-classifier"),
                    ("nvidia", None),
                ])
        elif hazard in ("cyclone", "hurricane", "tropical_storm"):
            if task == TaskType.HAZARD_CLASSIFICATION:
                candidates.extend([
                    ("huggingface", "aegis-hazard-classifier-v1"),
                    ("local", "local-distilbert-classifier"),
                    ("nvidia", None),
                ])

        # Task-based routing (when no hazard match)
        if not candidates:
            if task == TaskType.TEXT_CLASSIFICATION:
                candidates.extend([
                    ("huggingface", "aegis-hazard-classifier-v1"),
                    ("local", "local-distilbert-classifier"),
                ])
            elif task == TaskType.TEXT_SUMMARIZATION:
                candidates.extend([
                    ("huggingface", "aegis-nlp-summarizer-v1"),
                ])
            elif task == TaskType.TRANSLATION:
                candidates.extend([
                    ("huggingface", "aegis-translation-v1"),
                ])
            elif task == TaskType.NAMED_ENTITY_RECOGNITION:
                candidates.extend([
                    ("huggingface", "aegis-ner-v1"),
                    ("local", "local-spacy-ner"),
                ])
            elif task == TaskType.EMBEDDING:
                candidates.extend([
                    ("huggingface", "aegis-embedding-v1"),
                ])
            elif task == TaskType.SPEECH_TO_TEXT:
                candidates.extend([
                    ("huggingface", "aegis-stt-v1"),
                    ("local", "local-whisper-base"),
                ])
            elif task == TaskType.VICTIM_DETECTION:
                candidates.extend([
                    ("huggingface", "aegis-victim-detection-v1"),
                    ("local", None),
                ])
            elif task == TaskType.EXPLAINABILITY:
                candidates.extend([
                    ("huggingface", None),
                ])
            elif task == TaskType.REPORT_PARSING:
                candidates.extend([
                    ("huggingface", None),
                ])
            else:
                # Default: try all providers
                candidates.extend([
                    ("huggingface", None),
                    ("local", None),
                    ("nvidia", None),
                ])

        # Latency-based filtering
        if latency_requirement == "low":
            # Prefer local models for low latency
            candidates = [c for c in candidates if c[0] == "local"] + [c for c in candidates if c[0] != "local"]

        return candidates

    async def health(self) -> dict[str, Any]:
        """Health check for all registered providers."""
        result: dict[str, Any] = {}
        for name, provider in self._providers.items():
            result[name] = await provider.health()
        return result


# Singleton
_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
        from app.ai.providers.huggingface_provider import get_huggingface_provider
        from app.ai.providers.local_provider import get_local_provider

        _router.register_provider(get_huggingface_provider())
        _router.register_provider(get_local_provider())
    return _router
