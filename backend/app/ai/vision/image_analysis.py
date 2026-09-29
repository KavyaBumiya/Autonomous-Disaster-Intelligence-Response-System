"""
Image Analysis Pipeline — disaster imagery analysis.

Pipeline:
    image → validation → metadata extraction → geolocation
    → preprocessing → model selection → inference
    → confidence estimation → damage/victim/object analysis
    → geospatial mapping → explanation → structured result

Supports: satellite images, drone images, emergency photographs.
Does NOT identify private individuals.
"""
from __future__ import annotations

import base64
import structlog
from typing import Any

from app.ai.providers.base import PredictionResult, TaskType
from app.ai.router.model_router import get_model_router

logger = structlog.get_logger()


class ImageAnalysisPipeline:
    """Modular image analysis pipeline for disaster imagery."""

    def __init__(self) -> None:
        self._router = get_model_router()

    async def analyze(
        self,
        image_data: str | bytes,
        *,
        image_type: str = "unknown",  # satellite | drone | photograph | cctv
        hazard_context: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Full image analysis pipeline. Returns structured result."""
        result: dict[str, Any] = {
            "image_type": image_type,
            "hazard_context": hazard_context,
            "geolocation": {"lat": lat, "lng": lng},
            "damage_assessment": None,
            "victim_detection": None,
            "object_detection": None,
            "flood_mapping": None,
            "wildfire_detection": None,
            "confidence": 0.0,
            "explanation": "",
            "model_used": "",
            "fallback_used": False,
            "processing_steps": [],
        }

        try:
            # Step 1: Validate image
            validated = self._validate_image(image_data)
            if not validated:
                result["explanation"] = "Invalid or unsupported image"
                result["fallback_used"] = True
                return result
            result["processing_steps"].append("validation")

            # Step 2: Preprocessing
            processed = self._preprocess(validated)
            result["processing_steps"].append("preprocessing")

            # Whether any routed model produced a real prediction. Without this,
            # a run where every provider fell back returned HTTP 200 with all
            # fields null, `confidence: 0.0` and `fallback_used: false` -- a
            # successful-looking analysis of nothing, which reads as "the AI
            # looked and found no damage" rather than "no model could run".
            any_model_succeeded = False

            # Step 3: Route to appropriate model based on hazard context
            if hazard_context in ("flood", "flash_flood", "river_flood", "coastal_flood"):
                flood_result = await self._router.route(
                    TaskType.FLOOD_MAPPING,
                    processed,
                    hazard=hazard_context,
                    preferred_provider=kwargs.get("preferred_provider"),
                )
                if not flood_result.fallback_used:
                    result["flood_mapping"] = flood_result.to_dict()
                    result["confidence"] = flood_result.confidence
                    result["model_used"] = flood_result.model_id
                    any_model_succeeded = True
                    result["processing_steps"].append("flood_mapping")

            elif hazard_context in ("wildfire", "fire"):
                fire_result = await self._router.route(
                    TaskType.WILDFIRE_DETECTION,
                    processed,
                    hazard=hazard_context,
                    preferred_provider=kwargs.get("preferred_provider"),
                )
                if not fire_result.fallback_used:
                    result["wildfire_detection"] = fire_result.to_dict()
                    result["confidence"] = fire_result.confidence
                    result["model_used"] = fire_result.model_id
                    any_model_succeeded = True
                    result["processing_steps"].append("wildfire_detection")

            # Step 4: Damage assessment (always run)
            damage_result = await self._router.route(
                TaskType.DAMAGE_ASSESSMENT,
                processed,
                hazard=hazard_context,
                preferred_provider=kwargs.get("preferred_provider"),
            )
            if not damage_result.fallback_used:
                result["damage_assessment"] = damage_result.to_dict()
                result["confidence"] = max(result["confidence"], damage_result.confidence)
                result["model_used"] = damage_result.model_id
                any_model_succeeded = True
                result["processing_steps"].append("damage_assessment")

            # Step 5: Victim detection (if drone/photograph)
            if image_type in ("drone", "photograph"):
                victim_result = await self._router.route(
                    TaskType.VICTIM_DETECTION,
                    processed,
                    hazard=hazard_context,
                    preferred_provider=kwargs.get("preferred_provider"),
                )
                if not victim_result.fallback_used:
                    result["victim_detection"] = victim_result.to_dict()
                    any_model_succeeded = True
                    result["processing_steps"].append("victim_detection")

            # Step 6: Build explanation
            result["explanation"] = self._build_explanation(result)

            if not any_model_succeeded:
                # Every routed model fell back. Report that plainly instead of
                # returning a 200 full of nulls that reads as a clean bill of
                # health from a model that never ran.
                result["fallback_used"] = True
                result["explanation"] = (
                    "No vision model is available for this task. The image was "
                    "validated and preprocessed, but no provider returned a "
                    "prediction, so no damage, victim or hazard assessment is "
                    "shown."
                )


        except Exception as exc:
            logger.warning("image_analysis_failed", error=str(exc))
            result["explanation"] = f"Image analysis error: {exc}"
            result["fallback_used"] = True

        return result

    async def classify_damage(
        self,
        image_data: str | bytes,
        *,
        hazard_context: str | None = None,
        **kwargs: Any,
    ) -> PredictionResult:
        """Quick damage classification only."""
        processed = self._preprocess(image_data)
        return await self._router.route(
            TaskType.DAMAGE_ASSESSMENT,
            processed,
            hazard=hazard_context,
            preferred_provider=kwargs.get("preferred_provider"),
        )

    async def detect_victims(
        self,
        image_data: str | bytes,
        *,
        hazard_context: str | None = None,
        **kwargs: Any,
    ) -> PredictionResult:
        """Quick victim detection only."""
        processed = self._preprocess(image_data)
        return await self._router.route(
            TaskType.VICTIM_DETECTION,
            processed,
            hazard=hazard_context,
            preferred_provider=kwargs.get("preferred_provider"),
        )

    def _validate_image(self, image_data: str | bytes) -> str | None:
        """Validate and normalize image data. Returns base64 string or None."""
        try:
            if isinstance(image_data, bytes):
                return base64.b64encode(image_data).decode("utf-8")
            if isinstance(image_data, str):
                if image_data.startswith("data:image"):
                    b64 = image_data.split(",")[1]
                else:
                    b64 = image_data
                decoded = base64.b64decode(b64, validate=True)
                if len(decoded) < 10:
                    return None
                return b64
            return None
        except Exception:
            return None

    def _preprocess(self, image_data: str | bytes) -> str:
        """Preprocess image for model input. Returns base64 string."""
        if isinstance(image_data, bytes):
            return base64.b64encode(image_data).decode("utf-8")
        return image_data

    def _build_explanation(self, result: dict) -> str:
        parts = []
        if result["damage_assessment"]:
            parts.append(f"Damage: {result['damage_assessment'].get('prediction', 'unknown')}")
        if result["victim_detection"]:
            parts.append(f"Victims detected: {result['victim_detection'].get('prediction', {}).get('victim_count', 0) if isinstance(result['victim_detection'].get('prediction'), dict) else 0}")
        if result["flood_mapping"]:
            parts.append("Flood mapping completed")
        if result["wildfire_detection"]:
            parts.append("Wildfire detection completed")
        if not parts:
            return "No analysis results available"
        return ". ".join(parts)


# Singleton
_pipeline: ImageAnalysisPipeline | None = None


def get_image_pipeline() -> ImageAnalysisPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ImageAnalysisPipeline()
    return _pipeline
