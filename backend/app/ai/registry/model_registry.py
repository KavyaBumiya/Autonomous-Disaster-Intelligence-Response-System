"""
Model Registry — central registry for all AI/ML models in AEGIS.

Each model has:
    - model_id, model_name, provider, version
    - task, supported_hazards, supported_regions
    - input_schema, output_schema
    - latency, resource_requirements
    - confidence/calibration info
    - training data info
    - license, status, timestamp

The registry is the single source of truth for model discovery.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from app.ai.providers.base import ModelInfo, TaskType

logger = structlog.get_logger()


@dataclass
class ModelEntry:
    """Runtime model entry with health tracking."""
    info: ModelInfo
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used_at: str | None = None
    total_calls: int = 0
    total_failures: int = 0
    avg_latency_ms: float | None = None
    status: str = "registered"  # registered | loading | ready | error | deprecated


class ModelRegistry:
    """Thread-safe model registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: dict[str, ModelEntry] = {}

    def register(self, info: ModelInfo) -> None:
        """Register a model. Updates if already exists."""
        with self._lock:
            existing = self._models.get(info.model_id)
            if existing:
                existing.info = info
                logger.info("model_updated", model_id=info.model_id, provider=info.provider)
            else:
                self._models[info.model_id] = ModelEntry(info=info)
                logger.info("model_registered", model_id=info.model_id, provider=info.provider)

    def unregister(self, model_id: str) -> None:
        with self._lock:
            self._models.pop(model_id, None)

    def get(self, model_id: str) -> ModelEntry | None:
        with self._lock:
            return self._models.get(model_id)

    def list_all(self) -> list[ModelEntry]:
        with self._lock:
            return list(self._models.values())

    def list_by_task(self, task: TaskType) -> list[ModelEntry]:
        with self._lock:
            return [e for e in self._models.values() if e.info.task == task]

    def list_by_provider(self, provider: str) -> list[ModelEntry]:
        with self._lock:
            return [e for e in self._models.values() if e.info.provider == provider]

    def list_by_hazard(self, hazard: str) -> list[ModelEntry]:
        with self._lock:
            return [
                e for e in self._models.values()
                if hazard in e.info.supported_hazards or not e.info.supported_hazards
            ]

    def record_usage(self, model_id: str, latency_ms: float, success: bool) -> None:
        with self._lock:
            entry = self._models.get(model_id)
            if entry:
                entry.total_calls += 1
                entry.last_used_at = datetime.now(timezone.utc).isoformat()
                if not success:
                    entry.total_failures += 1
                if entry.avg_latency_ms is None:
                    entry.avg_latency_ms = latency_ms
                else:
                    entry.avg_latency_ms = 0.7 * entry.avg_latency_ms + 0.3 * latency_ms

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe snapshot for API responses."""
        with self._lock:
            return {
                model_id: {
                    "model_id": entry.info.model_id,
                    "model_name": entry.info.model_name,
                    "provider": entry.info.provider,
                    "version": entry.info.version,
                    "task": entry.info.task.value if isinstance(entry.info.task, TaskType) else entry.info.task,
                    "supported_hazards": entry.info.supported_hazards,
                    "supported_regions": entry.info.supported_regions,
                    "input_schema": entry.info.input_schema,
                    "output_schema": entry.info.output_schema,
                    "latency_ms": entry.info.latency_ms,
                    "resource_requirements": entry.info.resource_requirements,
                    "confidence_calibration": entry.info.confidence_calibration,
                    "training_data": entry.info.training_data,
                    "license": entry.info.license,
                    "status": entry.info.status,
                    "timestamp": entry.info.timestamp,
                    "registered_at": entry.registered_at,
                    "last_used_at": entry.last_used_at,
                    "total_calls": entry.total_calls,
                    "total_failures": entry.total_failures,
                    "avg_latency_ms": entry.avg_latency_ms,
                    "runtime_status": entry.status,
                }
                for model_id, entry in self._models.items()
            }


# Singleton
_registry: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def register_default_models() -> None:
    """Register all built-in AEGIS models."""
    registry = get_model_registry()

    # Hugging Face models
    from app.ai.providers.huggingface_provider import get_huggingface_provider
    hf = get_huggingface_provider()
    for model_info in hf.list_models():
        registry.register(model_info)

    # Local models (whisper, distilbert)
    from app.ai.providers.local_provider import get_local_provider
    local = get_local_provider()
    for model_info in local.list_models():
        registry.register(model_info)

    # NVIDIA NIM models (via existing ai_gateway)
    from app.ai.providers.nvidia_provider import get_nvidia_provider
    nvidia = get_nvidia_provider()
    for model_info in nvidia.list_models():
        registry.register(model_info)

    logger.info("default_models_registered", count=len(registry.list_all()))
