"""
Explainability Service — generates human-readable explanations for AI outputs.

Every prediction includes:
- prediction
- confidence
- evidence
- data sources
- model + version
- timestamp
- important features/signals
- uncertainty
- limitations

Never says "AI knows X will happen."
Instead: "Model estimates X% probability based on available signals."
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.ai.providers.base import PredictionResult, TaskType
from app.ai.router.model_router import get_model_router

logger = structlog.get_logger()


class ExplainabilityService:
    """Generates explainable AI outputs."""

    def __init__(self) -> None:
        self._router = get_model_router()

    async def explain(
        self,
        prediction_result: PredictionResult | None = None,
        *,
        text: str | None = None,
        hazard_type: str | None = None,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a full explanation for a prediction."""
        if prediction_result is None and text:
            prediction_result = await self._router.route(
                TaskType.EXPLAINABILITY,
                text,
                hazard=hazard_type,
                model_id=model_id,
            )

        if prediction_result is None:
            return self._empty_explanation("No prediction to explain")

        return {
            "prediction": prediction_result.prediction,
            "confidence": prediction_result.confidence,
            "confidence_label": self._confidence_label(prediction_result.confidence),
            "model": prediction_result.model_id,
            "model_version": prediction_result.model_version,
            "provider": prediction_result.provider,
            "generated_at": prediction_result.generated_at,
            "explanation": prediction_result.explanation,
            "evidence": prediction_result.evidence,
            "uncertainty": prediction_result.uncertainty,
            "limitations": prediction_result.limitations,
            "fallback_used": prediction_result.fallback_used,
            "fallback_reason": prediction_result.fallback_reason,
            "latency_ms": prediction_result.latency_ms,
            "human_readable": self._human_readable(prediction_result),
        }

    async def explain_prediction(
        self,
        task: TaskType,
        input_data: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run prediction + explanation in one call."""
        result = await self._router.route(task, input_data, **kwargs)
        return await self.explain(result)

    def _confidence_label(self, confidence: float) -> str:
        if confidence >= 0.9:
            return "very high"
        elif confidence >= 0.7:
            return "high"
        elif confidence >= 0.5:
            return "moderate"
        elif confidence >= 0.3:
            return "low"
        return "very low"

    def _human_readable(self, result: PredictionResult) -> str:
        if result.fallback_used:
            return (
                f"Prediction unavailable: {result.fallback_reason}. "
                "The system will continue operating with available data sources."
            )
        return (
            f"Model estimates {result.confidence:.0%} confidence "
            f"({self._confidence_label(result.confidence)}) for: {result.prediction}. "
            f"Based on: {result.explanation}"
        )

    def _empty_explanation(self, reason: str) -> dict[str, Any]:
        return {
            "prediction": None,
            "confidence": 0.0,
            "confidence_label": "none",
            "model": None,
            "model_version": None,
            "provider": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "explanation": reason,
            "evidence": [],
            "uncertainty": "No prediction available",
            "limitations": [reason],
            "fallback_used": True,
            "fallback_reason": reason,
            "latency_ms": 0.0,
            "human_readable": f"Prediction unavailable: {reason}",
        }


# Singleton
_explainability: ExplainabilityService | None = None


def get_explainability_service() -> ExplainabilityService:
    global _explainability
    if _explainability is None:
        _explainability = ExplainabilityService()
    return _explainability
