"""
Disaster NLP Pipeline — structured analysis of emergency text reports.

Pipeline:
    text → language detection → normalization → hazard classification
    → entity extraction → location extraction → severity extraction
    → urgency estimation → duplicate detection → credibility scoring
    → structured incident JSON

Uses the model router for inference — never hard-codes a provider.
"""
from __future__ import annotations

import structlog
from typing import Any

from app.ai.providers.base import PredictionResult, TaskType
from app.ai.router.model_router import get_model_router

logger = structlog.get_logger()


class DisasterNLP:
    """NLP pipeline for disaster report analysis."""

    def __init__(self) -> None:
        self._router = get_model_router()

    async def analyze(self, text: str, **kwargs: Any) -> dict[str, Any]:
        """Full NLP pipeline. Returns structured analysis."""
        if not text or not text.strip():
            return self._empty_result("empty text")

        result: dict[str, Any] = {
            "original_text": text,
            "language": None,
            "hazard_type": None,
            "hazard_confidence": 0.0,
            "entities": [],
            "location": None,
            "severity": None,
            "urgency": None,
            "credibility_score": 0.0,
            "duplicate_of": None,
            "structured_output": {},
            "explanation": "",
            "model_used": "",
            "fallback_used": False,
        }

        try:
            # Step 1: Language detection
            result["language"] = self._detect_language(text)

            # Step 2: Hazard classification
            hazard_result = await self._router.route(
                TaskType.HAZARD_CLASSIFICATION,
                text,
                hazard=kwargs.get("hazard"),
                preferred_provider=kwargs.get("preferred_provider"),
            )
            if not hazard_result.fallback_used:
                result["hazard_type"] = hazard_result.prediction
                result["hazard_confidence"] = hazard_result.confidence
                result["model_used"] = hazard_result.model_id
            else:
                # Fallback to keyword classification
                result["hazard_type"] = self._keyword_classify(text)
                result["hazard_confidence"] = 0.4
                result["fallback_used"] = True

            # Step 3: Entity extraction
            ner_result = await self._router.route(
                TaskType.NAMED_ENTITY_RECOGNITION,
                text,
                preferred_provider=kwargs.get("preferred_provider"),
            )
            if not ner_result.fallback_used:
                result["entities"] = ner_result.prediction if isinstance(ner_result.prediction, list) else []

            # Step 4: Location extraction
            result["location"] = self._extract_location(text, result["entities"])

            # Step 5: Severity + urgency
            result["severity"] = self._estimate_severity(text)
            result["urgency"] = self._estimate_urgency(text)

            # Step 6: Credibility scoring
            result["credibility_score"] = self._credibility_score(text, result)

            # Step 7: Structured output
            result["structured_output"] = {
                "hazard_type": result["hazard_type"],
                "location": result["location"],
                "severity": result["severity"],
                "urgency": result["urgency"],
                "entities": result["entities"],
                "language": result["language"],
                "confidence": result["hazard_confidence"],
            }

            result["explanation"] = (
                f"Classified as {result['hazard_type']} with "
                f"{result['hazard_confidence']:.0%} confidence. "
                f"Urgency: {result['urgency']}. "
                f"Credibility: {result['credibility_score']:.0%}."
            )

        except Exception as exc:
            logger.warning("nlp_pipeline_failed", error=str(exc))
            result["explanation"] = f"NLP pipeline error: {exc}"
            result["fallback_used"] = True

        return result

    async def classify(self, text: str, **kwargs: Any) -> PredictionResult:
        """Quick hazard classification only."""
        return await self._router.route(
            TaskType.HAZARD_CLASSIFICATION,
            text,
            hazard=kwargs.get("hazard"),
            preferred_provider=kwargs.get("preferred_provider"),
        )

    async def extract_entities(self, text: str, **kwargs: Any) -> PredictionResult:
        """Quick entity extraction only."""
        return await self._router.route(
            TaskType.NAMED_ENTITY_RECOGNITION,
            text,
            preferred_provider=kwargs.get("preferred_provider"),
        )

    async def summarize(self, text: str, **kwargs: Any) -> PredictionResult:
        """Summarize a disaster report."""
        return await self._router.route(
            TaskType.TEXT_SUMMARIZATION,
            text,
            preferred_provider=kwargs.get("preferred_provider"),
        )

    def _detect_language(self, text: str) -> str:
        try:
            from langdetect import detect, LangDetectException
            return detect(text[:200])
        except Exception:
            return "unknown"

    def _keyword_classify(self, text: str) -> str:
        """Fallback keyword-based classification."""
        text_lower = text.lower()
        keywords = {
            "flood": ["flood", "flooded", "flooding", "inundated", "waterlogged", "submerged"],
            "earthquake": ["earthquake", "quake", "tremor", "seismic", "aftershock"],
            "fire": ["fire", "blaze", "burning", "flames", "wildfire", "smoke"],
            "cyclone": ["cyclone", "hurricane", "typhoon", "storm", "tornado"],
            "landslide": ["landslide", "mudslide", "rockfall", "debris"],
            "tsunami": ["tsunami", "tidal wave"],
        }
        scores: dict[str, int] = {}
        for dtype, kws in keywords.items():
            count = sum(1 for kw in kws if kw in text_lower)
            if count:
                scores[dtype] = count
        return max(scores, key=scores.get) if scores else "unknown"

    def _extract_location(self, text: str, entities: list) -> str | None:
        """Extract location from NER entities."""
        for ent in entities:
            if isinstance(ent, dict) and ent.get("entity") in ("GPE", "LOC", "FAC"):
                return ent.get("text")
        return None

    def _estimate_severity(self, text: str) -> str:
        text_lower = text.lower()
        critical_words = ["trapped", "missing", "dead", "death", "collapsed", "destroyed", "emergency"]
        high_words = ["injured", "damaged", "flooded", "fire", "evacuate"]
        medium_words = ["affected", "disrupted", "blocked", "warning"]

        if any(w in text_lower for w in critical_words):
            return "critical"
        elif any(w in text_lower for w in high_words):
            return "high"
        elif any(w in text_lower for w in medium_words):
            return "medium"
        return "low"

    def _estimate_urgency(self, text: str) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["sos", "emergency", "urgent", "help", "trapped", "now"]):
            return "critical"
        elif any(w in text_lower for w in ["soon", "rising", "spreading", "warning"]):
            return "high"
        return "medium"

    def _credibility_score(self, text: str, result: dict) -> float:
        score = 0.5
        if result["language"] != "unknown":
            score += 0.1
        if result["hazard_type"] != "unknown":
            score += 0.2
        if result["entities"]:
            score += 0.1
        if len(text) > 50:
            score += 0.1
        return min(1.0, score)

    def _empty_result(self, reason: str) -> dict[str, Any]:
        return {
            "original_text": "",
            "language": "unknown",
            "hazard_type": None,
            "hazard_confidence": 0.0,
            "entities": [],
            "location": None,
            "severity": None,
            "urgency": None,
            "credibility_score": 0.0,
            "duplicate_of": None,
            "structured_output": {},
            "explanation": reason,
            "model_used": "",
            "fallback_used": True,
        }


# Singleton
_nlp: DisasterNLP | None = None


def get_disaster_nlp() -> DisasterNLP:
    global _nlp
    if _nlp is None:
        _nlp = DisasterNLP()
    return _nlp
