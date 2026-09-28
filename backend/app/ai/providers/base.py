"""
AIModelProvider — base abstraction for all AI/ML inference providers.

Every provider must implement:
    - health() → provider availability
    - list_models() → available models
    - predict(task, input, model_id) → structured prediction

The rest of AEGIS calls this abstraction — never a specific provider.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    """Supported AI/ML task types."""
    TEXT_CLASSIFICATION = "text_classification"
    TEXT_GENERATION = "text_generation"
    TEXT_SUMMARIZATION = "text_summarization"
    TRANSLATION = "translation"
    NAMED_ENTITY_RECOGNITION = "ner"
    QUESTION_ANSWERING = "question_answering"
    IMAGE_CLASSIFICATION = "image_classification"
    OBJECT_DETECTION = "object_detection"
    IMAGE_SEGMENTATION = "image_segmentation"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    EMBEDDING = "embedding"
    SEMANTIC_SEARCH = "semantic_search"
    TIME_SERIES_FORECAST = "time_series_forecast"
    ANOMALY_DETECTION = "anomaly_detection"
    HAZARD_CLASSIFICATION = "hazard_classification"
    DAMAGE_ASSESSMENT = "damage_assessment"
    VICTIM_DETECTION = "victim_detection"
    FLOOD_MAPPING = "flood_mapping"
    WILDFIRE_DETECTION = "wildfire_detection"
    EXPLAINABILITY = "explainability"
    REPORT_PARSING = "report_parsing"
    URGENCY_CLASSIFICATION = "urgency_classification"
    CREDIBILITY_SCORING = "credibility_scoring"


class Modality(str, Enum):
    """Input/output modalities."""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    MULTIMODAL = "multimodal"
    TIME_SERIES = "time_series"
    GEOSPATIAL = "geospatial"


@dataclass
class ModelInfo:
    """Metadata for a registered model."""
    model_id: str
    model_name: str
    provider: str
    version: str
    task: TaskType
    supported_hazards: list[str] = field(default_factory=list)
    supported_regions: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    confidence_calibration: dict[str, Any] = field(default_factory=dict)
    training_data: str | None = None
    license: str | None = None
    status: str = "experimental"  # experimental | staging | production | deprecated
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionResult:
    """Structured prediction result — every AI output must be explainable."""
    prediction: Any
    confidence: float
    model_id: str
    model_version: str
    provider: str
    task: TaskType
    generated_at: str
    explanation: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    uncertainty: str = ""
    limitations: list[str] = field(default_factory=list)
    input_summary: str = ""
    latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction": self.prediction,
            "confidence": self.confidence,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "provider": self.provider,
            "task": self.task.value if isinstance(self.task, TaskType) else self.task,
            "generated_at": self.generated_at,
            "explanation": self.explanation,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "limitations": self.limitations,
            "input_summary": self.input_summary,
            "latency_ms": self.latency_ms,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
        }


class AIModelProvider(ABC):
    """Base class for all AI/ML model providers.

    Guarantees:
        - Never raises — returns fallback results on failure
        - Every result includes confidence + explanation
        - Every result includes model version + provider attribution
        - Timeout handling is built-in
        - All errors are logged with structured logging
    """

    provider_name: str = "base"
    supported_tasks: list[TaskType] = []

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Check provider availability. Never raises."""
        ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """List available models from this provider. Synchronous — returns static info."""
        ...

    @abstractmethod
    async def predict(
        self,
        task: TaskType,
        input_data: Any,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> PredictionResult:
        """Run inference. Never raises — returns fallback on failure."""
        ...

    async def embed(self, texts: list[str], model_id: str | None = None) -> list[list[float]]:
        """Generate embeddings. Default: not supported."""
        raise NotImplementedError(f"{self.provider_name} does not support embeddings")

    def supports(self, task: TaskType) -> bool:
        return task in self.supported_tasks
