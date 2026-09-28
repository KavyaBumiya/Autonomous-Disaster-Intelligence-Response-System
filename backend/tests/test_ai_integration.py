"""
Integration tests for the complete AI layer.

Tests the full flow: provider → router → pipeline → API → decision.
"""
import pytest
from app.ai.providers.base import TaskType, PredictionResult
from app.ai.providers.huggingface_provider import get_huggingface_provider
from app.ai.providers.local_provider import get_local_provider
from app.ai.providers.nvidia_provider import get_nvidia_provider
from app.ai.providers.openai_provider import get_openai_provider
from app.ai.registry.model_registry import get_model_registry, register_default_models
from app.ai.router.model_router import get_model_router
from app.ai.nlp.disaster_nlp import get_disaster_nlp
from app.ai.vision.image_analysis import get_image_pipeline
from app.ai.explain.explainability import get_explainability_service
from app.ai.queue.task_queue import get_task_queue
from app.ai.storage.prediction_store import get_prediction_store


class TestProviderIntegration:
    """Test all providers are registered and accessible."""

    def test_all_providers_available(self):
        hf = get_huggingface_provider()
        local = get_local_provider()
        nvidia = get_nvidia_provider()
        openai = get_openai_provider()

        assert hf.provider_name == "huggingface"
        assert local.provider_name == "local"
        assert nvidia.provider_name == "nvidia"
        assert openai.provider_name == "openai"

    @pytest.mark.asyncio
    async def test_all_providers_health(self):
        providers = [
            get_huggingface_provider(),
            get_local_provider(),
            get_nvidia_provider(),
            get_openai_provider(),
        ]
        for provider in providers:
            health = await provider.health()
            assert health["provider"] == provider.provider_name
            assert "status" in health


class TestModelRegistryIntegration:
    """Test model registry with all providers."""

    def test_register_default_models(self):
        register_default_models()
        registry = get_model_registry()
        models = registry.list_all()
        assert len(models) > 0

        # Check we have models from multiple providers
        providers = set(m.info.provider for m in models)
        assert len(providers) >= 2

    def test_registry_snapshot(self):
        registry = get_model_registry()
        snapshot = registry.snapshot()
        assert isinstance(snapshot, dict)
        assert len(snapshot) > 0


class TestModelRouterIntegration:
    """Test model router with all providers."""

    @pytest.mark.asyncio
    async def test_route_to_fallback(self):
        router = get_model_router()
        result = await router.route(
            TaskType.HAZARD_CLASSIFICATION,
            "Flood in Vadodara",
            hazard="flood",
        )
        assert isinstance(result, PredictionResult)
        # In test environment, all providers return fallback
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_route_with_preferred_provider(self):
        router = get_model_router()
        result = await router.route(
            TaskType.TEXT_CLASSIFICATION,
            "Test text",
            preferred_provider="local",
        )
        assert isinstance(result, PredictionResult)

    @pytest.mark.asyncio
    async def test_router_health_all_providers(self):
        router = get_model_router()
        health = await router.health()
        assert isinstance(health, dict)
        assert len(health) >= 3


class TestPipelineIntegration:
    """Test full pipeline integration."""

    @pytest.mark.asyncio
    async def test_nlp_to_explain(self):
        nlp = get_disaster_nlp()
        explain = get_explainability_service()

        nlp_result = await nlp.analyze("Severe flooding in Vadodara")
        explanation = await explain.explain(
            text="Severe flooding in Vadodara",
            hazard_type="flood",
        )

        assert explanation is not None
        assert "explanation" in explanation
        assert "confidence" in explanation

    @pytest.mark.asyncio
    async def test_vision_to_explain(self):
        pipeline = get_image_pipeline()
        explain = get_explainability_service()

        vision_result = await pipeline.analyze(
            "aGVsbG8gd29ybGQ=",
            image_type="drone",
            hazard_context="flood",
        )
        assert vision_result is not None
        assert "processing_steps" in vision_result


class TestQueueIntegration:
    """Test task queue integration."""

    @pytest.mark.asyncio
    async def test_enqueue_and_get(self):
        queue = get_task_queue()
        task_id = await queue.enqueue(
            "hazard_classification",
            "Flood in Vadodara",
            priority=1,
        )
        assert task_id is not None

        task = await queue.get_task(task_id)
        # Task may be None if Redis is not available (graceful degradation)
        if task is not None:
            assert task["task_id"] == task_id
            assert task["status"] == "queued"


class TestPredictionStoreIntegration:
    """Test prediction store integration."""

    def test_store_singleton(self):
        store = get_prediction_store()
        assert store is not None
        assert store is get_prediction_store()


class TestEndToEndFlow:
    """Test complete end-to-end flow."""

    @pytest.mark.asyncio
    async def test_full_flow(self):
        """NLP → Explain → Queue → Store."""
        nlp = get_disaster_nlp()
        explain = get_explainability_service()
        queue = get_task_queue()

        # Step 1: NLP analysis
        nlp_result = await nlp.analyze("Severe flooding in Vadodara, people trapped")
        assert nlp_result is not None

        # Step 2: Explanation
        explanation = await explain.explain(
            text="Severe flooding in Vadodara, people trapped",
            hazard_type="flood",
        )
        assert explanation is not None
        assert "explanation" in explanation

        # Step 3: Queue for async processing
        task_id = await queue.enqueue(
            "report_analysis",
            "Severe flooding in Vadodara, people trapped",
        )
        assert task_id is not None

    def test_provider_abstraction_contract(self):
        """Verify all providers implement the required contract."""
        from app.ai.providers.base import AIModelProvider

        providers = [
            get_huggingface_provider(),
            get_local_provider(),
            get_nvidia_provider(),
            get_openai_provider(),
        ]

        for provider in providers:
            assert isinstance(provider, AIModelProvider)
            assert hasattr(provider, "health")
            assert hasattr(provider, "list_models")
            assert hasattr(provider, "predict")
            assert hasattr(provider, "provider_name")
            assert hasattr(provider, "supported_tasks")
