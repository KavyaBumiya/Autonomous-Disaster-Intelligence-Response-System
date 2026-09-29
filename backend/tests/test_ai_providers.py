"""
Tests for AI provider abstraction layer.

Tests:
- Provider health checks
- Model listing
- Prediction with fallback
- Provider routing
- Model registry
"""
import os
from unittest.mock import patch

import pytest
from app.ai.providers.base import TaskType, PredictionResult
from app.ai.providers.huggingface_provider import HuggingFaceProvider, get_huggingface_provider
from app.ai.providers.local_provider import LocalModelProvider, get_local_provider
from app.ai.providers.nvidia_provider import NvidiaProvider, get_nvidia_provider
from app.ai.registry.model_registry import ModelRegistry, get_model_registry, register_default_models
from app.ai.router.model_router import ModelRouter, get_model_router
from app.core.config import get_settings


def _no_token_init(self):
    """Provider init that behaves exactly as if HUGGINGFACE_TOKEN were unset."""
    self._tokenizers = {}
    self._hf_token = ""
    from app.core.config import get_settings

    settings = get_settings()
    self._api_base = settings.huggingface_api_base
    self._timeout = settings.huggingface_timeout_seconds


class TestProviderBase:
    """Test the base provider abstraction."""

    def test_task_type_enum(self):
        assert TaskType.HAZARD_CLASSIFICATION.value == "hazard_classification"
        assert TaskType.TEXT_CLASSIFICATION.value == "text_classification"
        assert TaskType.EMBEDDING.value == "embedding"

    def test_prediction_result_to_dict(self):
        result = PredictionResult(
            prediction="flood",
            confidence=0.85,
            model_id="test-model",
            model_version="1.0.0",
            provider="test",
            task=TaskType.HAZARD_CLASSIFICATION,
            generated_at="2026-01-01T00:00:00Z",
        )
        d = result.to_dict()
        assert d["prediction"] == "flood"
        assert d["confidence"] == 0.85
        assert d["model_id"] == "test-model"
        assert d["provider"] == "test"


class TestHuggingFaceProvider:
    """Test Hugging Face provider."""

    @pytest.mark.asyncio
    async def test_health_no_token(self, monkeypatch):
        # Force the unconfigured case explicitly. Relying on the ambient
        # environment having no HUGGINGFACE_TOKEN made this test pass or fail
        # depending on a developer's local .env.
        monkeypatch.setattr(HuggingFaceProvider, "__init__", _no_token_init)
        provider = HuggingFaceProvider()
        health = await provider.health()
        assert health["provider"] == "huggingface"
        assert health["status"] == "OFFLINE"
        assert "HUGGINGFACE_TOKEN" in health["reason"]

    def test_list_models(self):
        provider = HuggingFaceProvider()
        models = provider.list_models()
        assert len(models) > 0
        model_ids = [m.model_id for m in models]
        assert "aegis-hazard-classifier-v1" in model_ids
        assert "aegis-damage-assessment-v1" in model_ids

    @pytest.mark.asyncio
    async def test_predict_fallback_no_token(self, monkeypatch):
        monkeypatch.setattr(HuggingFaceProvider, "__init__", _no_token_init)
        provider = HuggingFaceProvider()
        result = await provider.predict(
            TaskType.HAZARD_CLASSIFICATION,
            "Flood in Vadodara",
        )
        assert result.fallback_used is True
        assert result.confidence == 0.0
        assert "HUGGINGFACE_TOKEN" in result.fallback_reason

    @pytest.mark.asyncio
    async def test_supported_tasks(self):
        provider = HuggingFaceProvider()
        assert provider.supports(TaskType.TEXT_CLASSIFICATION)
        assert provider.supports(TaskType.EMBEDDING)
        assert not provider.supports(TaskType.TIME_SERIES_FORECAST)


class TestLocalProvider:
    """Test local model provider."""

    @pytest.mark.asyncio
    async def test_health(self):
        provider = LocalModelProvider()
        health = await provider.health()
        assert health["provider"] == "local"
        assert health["status"] in ("ONLINE", "OFFLINE")

    def test_list_models(self):
        provider = LocalModelProvider()
        models = provider.list_models()
        assert len(models) >= 3
        model_ids = [m.model_id for m in models]
        assert "local-whisper-base" in model_ids
        assert "local-distilbert-classifier" in model_ids

    @pytest.mark.asyncio
    async def test_predict_fallback(self):
        provider = LocalModelProvider()
        result = await provider.predict(
            TaskType.TEXT_CLASSIFICATION,
            "Test text",
        )
        assert isinstance(result, PredictionResult)
        assert result.provider == "local"


class TestNvidiaProvider:
    """Test NVIDIA NIM provider."""

    @pytest.mark.asyncio
    async def test_health_no_key(self):
        # backend/.env is auto-loaded by pydantic-settings, so a real key is
        # present in any normal run. This test is about the no-key path.
        #
        # Patch get_settings *inside nvidia_service* rather than mutating
        # os.environ + clearing get_settings' lru_cache: clearing the
        # process-wide cache is visible to every later test module, which
        # re-read .env and breaks tests that rely on the cached values.
        from types import SimpleNamespace

        import app.integrations.ai.nvidia_service as nvidia_service

        real = get_settings()
        fake = SimpleNamespace(
            nvidia_api_key="",
            nvidia_base_url=real.nvidia_base_url,
            nvidia_timeout_seconds=real.nvidia_timeout_seconds,
        )
        with patch.object(nvidia_service, "get_settings", return_value=fake):
            provider = NvidiaProvider()
            health = await provider.health()

        assert health["provider"] == "nvidia"
        assert health["status"] == "OFFLINE"

    def test_list_models(self):
        provider = NvidiaProvider()
        models = provider.list_models()
        assert len(models) >= 1
        assert models[0].provider == "nvidia"


class TestModelRegistry:
    """Test model registry."""

    def test_register_and_get(self):
        registry = ModelRegistry()
        from app.ai.providers.base import ModelInfo
        info = ModelInfo(
            model_id="test-model",
            model_name="test",
            provider="test",
            version="1.0.0",
            task=TaskType.TEXT_CLASSIFICATION,
        )
        registry.register(info)
        entry = registry.get("test-model")
        assert entry is not None
        assert entry.info.model_id == "test-model"

    def test_list_by_task(self):
        registry = ModelRegistry()
        from app.ai.providers.base import ModelInfo
        registry.register(ModelInfo(
            model_id="m1", model_name="m1", provider="test", version="1",
            task=TaskType.TEXT_CLASSIFICATION,
        ))
        registry.register(ModelInfo(
            model_id="m2", model_name="m2", provider="test", version="1",
            task=TaskType.EMBEDDING,
        ))
        results = registry.list_by_task(TaskType.TEXT_CLASSIFICATION)
        assert len(results) == 1
        assert results[0].info.model_id == "m1"

    def test_record_usage(self):
        registry = ModelRegistry()
        from app.ai.providers.base import ModelInfo
        registry.register(ModelInfo(
            model_id="test-model", model_name="test", provider="test",
            version="1", task=TaskType.TEXT_CLASSIFICATION,
        ))
        registry.record_usage("test-model", 100.0, True)
        entry = registry.get("test-model")
        assert entry.total_calls == 1
        assert entry.avg_latency_ms == 100.0

    def test_snapshot(self):
        registry = ModelRegistry()
        from app.ai.providers.base import ModelInfo
        registry.register(ModelInfo(
            model_id="test-model", model_name="test", provider="test",
            version="1", task=TaskType.TEXT_CLASSIFICATION,
        ))
        snap = registry.snapshot()
        assert "test-model" in snap
        assert snap["test-model"]["model_id"] == "test-model"


class TestModelRouter:
    """Test model router."""

    @pytest.mark.asyncio
    async def test_route_fallback(self):
        router = ModelRouter()
        result = await router.route(
            TaskType.HAZARD_CLASSIFICATION,
            "Flood in Vadodara",
            hazard="flood",
        )
        assert isinstance(result, PredictionResult)
        # Should get a fallback result (no real models configured in test)
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_health(self):
        router = get_model_router()
        health = await router.health()
        assert isinstance(health, dict)
        assert len(health) > 0

    @pytest.mark.asyncio
    async def test_select_candidates_flood(self):
        router = ModelRouter()
        candidates = router._select_candidates(
            TaskType.HAZARD_CLASSIFICATION,
            hazard="flood",
            resolution="city",
            latency_requirement="normal",
            hardware="cpu",
        )
        assert len(candidates) > 0
        # Should include HF and local providers
        provider_names = [c[0] for c in candidates]
        assert "huggingface" in provider_names or "local" in provider_names


class TestProviderSingletons:
    """Test provider singleton pattern."""

    def test_huggingface_singleton(self):
        p1 = get_huggingface_provider()
        p2 = get_huggingface_provider()
        assert p1 is p2

    def test_local_singleton(self):
        p1 = get_local_provider()
        p2 = get_local_provider()
        assert p1 is p2

    def test_nvidia_singleton(self):
        p1 = get_nvidia_provider()
        p2 = get_nvidia_provider()
        assert p1 is p2

    def test_router_singleton(self):
        r1 = get_model_router()
        r2 = get_model_router()
        assert r1 is r2

    def test_registry_singleton(self):
        r1 = get_model_registry()
        r2 = get_model_registry()
        assert r1 is r2
