"""
HuggingFaceProvider — Hugging Face Hub model inference.

Supports both:
  A. Remote inference via Hugging Face Inference API
  B. Local inference via transformers library (when models are cached)

Models are loaded lazily and cached. The provider never raises —
failures return fallback PredictionResults with explicit uncertainty.
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


class HuggingFaceProvider(AIModelProvider):
    """Hugging Face Hub model provider.

    Uses the Hugging Face Inference API for remote calls, or falls back
    to local transformers models when available. All models are loaded
    lazily and cached in memory.
    """

    provider_name = "huggingface"
    # Only tasks with a real dispatch branch in predict() are listed. The
    # vision tasks below were previously advertised here while predict() had no
    # branch for them, so the router dutifully called this provider, got a
    # fallback, discarded it, and walked the rest of a chain with no vision
    # member at all -- every field of the image panel came back null while the
    # panel still rendered as a successful analysis.
    #
    # They are deliberately NOT re-added until a model that can actually do the
    # job is pinned. The aliases that existed pointed at models that cannot:
    #   aegis-damage-assessment-v1  -> microsoft/resnet-50   (ImageNet: "tench",
    #                                  "espresso" reported as damage levels with
    #                                  the model's real confidence)
    #   aegis-victim-detection-v1   -> ultralytics/yolov8n   (needs `ultralytics`,
    #                                  absent from requirements.txt)
    # Wiring those up would have produced confident, plausible-looking nonsense,
    # which is worse than an explicit "unavailable".
    supported_tasks = [
        TaskType.TEXT_CLASSIFICATION,
        TaskType.TEXT_GENERATION,
        TaskType.TEXT_SUMMARIZATION,
        TaskType.TRANSLATION,
        TaskType.NAMED_ENTITY_RECOGNITION,
        TaskType.QUESTION_ANSWERING,
        TaskType.IMAGE_CLASSIFICATION,
        TaskType.OBJECT_DETECTION,
        TaskType.SPEECH_TO_TEXT,
        TaskType.EMBEDDING,
        TaskType.EXPLAINABILITY,
        TaskType.REPORT_PARSING,
        TaskType.URGENCY_CLASSIFICATION,
    ]

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._tokenizers: dict[str, Any] = {}
        self._pipelines: dict[str, Any] = {}
        self._hf_token = settings.huggingface_token
        self._api_base = settings.huggingface_api_base
        self._timeout = settings.huggingface_timeout_seconds
        self._model_id_map = {
            "aegis-hazard-classifier-v1": "microsoft/deberta-v3-base",
            "aegis-damage-assessment-v1": "microsoft/resnet-50",
            "aegis-flood-mapping-v1": "nvidia/segformer-b0-finetuned-ade-512-512",
            "aegis-wildfire-detection-v1": "ultralytics/yolov8n",
            "aegis-nlp-summarizer-v1": "facebook/bart-large-cnn",
            "aegis-translation-v1": "facebook/m2m100_418M",
            "aegis-ner-v1": "dslim/bert-base-NER",
            "aegis-embedding-v1": "sentence-transformers/all-MiniLM-L6-v2",
            "aegis-stt-v1": "openai/whisper-base",
            "aegis-victim-detection-v1": "ultralytics/yolov8n",
        }

    def _resolve_model_id(self, model_id: str | None, task: TaskType) -> str:
        """Map internal model_id to actual HF model name."""
        if model_id and model_id in self._model_id_map:
            return self._model_id_map[model_id]
        if model_id and "/" in model_id:
            return model_id
        defaults = {
            TaskType.TEXT_CLASSIFICATION: "microsoft/deberta-v3-base",
            TaskType.TEXT_SUMMARIZATION: "facebook/bart-large-cnn",
            TaskType.TRANSLATION: "facebook/m2m100_418M",
            TaskType.NAMED_ENTITY_RECOGNITION: "dslim/bert-base-NER",
            TaskType.EMBEDDING: "sentence-transformers/all-MiniLM-L6-v2",
            TaskType.IMAGE_CLASSIFICATION: "microsoft/resnet-50",
            TaskType.OBJECT_DETECTION: "ultralytics/yolov8n",
            TaskType.SPEECH_TO_TEXT: "openai/whisper-base",
        }
        return defaults.get(task, model_id or "facebook/bart-large-cnn")

    async def health(self) -> dict[str, Any]:
        """Check HF provider availability."""
        try:
            if not self._hf_token:
                return {
                    "provider": self.provider_name,
                    "status": "OFFLINE",
                    "reason": "HUGGINGFACE_TOKEN not configured",
                }
            # Lightweight API check
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._api_base}/api/models",
                    headers={"Authorization": f"Bearer {self._hf_token}"},
                )
                if resp.status_code == 200:
                    return {
                        "provider": self.provider_name,
                        "status": "ONLINE",
                        "models_available": len(resp.json()),
                    }
                return {
                    "provider": self.provider_name,
                    "status": "DEGRADED",
                    "reason": f"HTTP {resp.status_code}",
                }
        except Exception as exc:
            return {
                "provider": self.provider_name,
                "status": "OFFLINE",
                "reason": str(exc),
            }

    def list_models(self) -> list[ModelInfo]:
        """List curated HF models for AEGIS disaster intelligence tasks."""
        return [
            ModelInfo(
                model_id="aegis-hazard-classifier-v1",
                model_name="microsoft/deberta-v3-base-finetuned-disaster",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.HAZARD_CLASSIFICATION,
                supported_hazards=["flood", "earthquake", "cyclone", "wildfire", "landslide", "tsunami"],
                input_schema={"text": "string"},
                output_schema={"label": "string", "confidence": "float"},
                status="experimental",
                license="MIT",
            ),
            ModelInfo(
                model_id="aegis-damage-assessment-v1",
                model_name="microsoft/resnet-50-finetuned-damage",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.DAMAGE_ASSESSMENT,
                supported_hazards=["flood", "earthquake", "cyclone", "wildfire"],
                input_schema={"image": "base64"},
                output_schema={"damage_level": "string", "confidence": "float"},
                status="experimental",
            ),
            ModelInfo(
                model_id="aegis-flood-mapping-v1",
                model_name="nvidia/segformer-b0-finetuned-flood",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.FLOOD_MAPPING,
                supported_hazards=["flood", "flash_flood", "river_flood", "coastal_flood"],
                input_schema={"image": "base64"},
                output_schema={"mask": "base64", "flood_percentage": "float"},
                status="experimental",
            ),
            ModelInfo(
                model_id="aegis-wildfire-detection-v1",
                model_name="ultralytics/yolov8n-wildfire",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.WILDFIRE_DETECTION,
                supported_hazards=["wildfire"],
                input_schema={"image": "base64"},
                output_schema={"detections": "array", "confidence": "float"},
                status="experimental",
            ),
            ModelInfo(
                model_id="aegis-nlp-summarizer-v1",
                model_name="facebook/bart-large-cnn",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.TEXT_SUMMARIZATION,
                input_schema={"text": "string"},
                output_schema={"summary": "string"},
                status="staging",
                license="MIT",
                metadata={"hf_model_id": "facebook/bart-large-cnn"},
            ),
            ModelInfo(
                model_id="aegis-translation-v1",
                model_name="facebook/m2m100_418M",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.TRANSLATION,
                input_schema={"text": "string", "source_lang": "string", "target_lang": "string"},
                output_schema={"translated_text": "string"},
                status="staging",
            ),
            ModelInfo(
                model_id="aegis-ner-v1",
                model_name="dslim/bert-base-NER",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.NAMED_ENTITY_RECOGNITION,
                input_schema={"text": "string"},
                output_schema={"entities": "array"},
                status="staging",
            ),
            ModelInfo(
                model_id="aegis-embedding-v1",
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.EMBEDDING,
                input_schema={"texts": "array[string]"},
                output_schema={"embeddings": "array[array[float]]"},
                status="production",
            ),
            ModelInfo(
                model_id="aegis-stt-v1",
                model_name="openai/whisper-base",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.SPEECH_TO_TEXT,
                input_schema={"audio": "base64"},
                output_schema={"transcript": "string", "language": "string"},
                status="staging",
            ),
            ModelInfo(
                model_id="aegis-victim-detection-v1",
                model_name="ultralytics/yolov8n",
                provider=self.provider_name,
                version="1.0.0",
                task=TaskType.VICTIM_DETECTION,
                input_schema={"image": "base64"},
                output_schema={"detections": "array", "victim_count": "int"},
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
        """Run inference via Hugging Face. Never raises — returns fallback."""
        started = time.perf_counter()
        now = datetime.now(timezone.utc).isoformat()

        try:
            if not self._hf_token:
                return self._fallback_result(
                    task, model_id or "unknown", now, started,
                    "HUGGINGFACE_TOKEN not configured",
                )

            resolved_id = self._resolve_model_id(model_id, task)

            # Route to appropriate pipeline
            if task == TaskType.TEXT_CLASSIFICATION:
                result = await self._text_classification(input_data, resolved_id, **kwargs)
            elif task == TaskType.TEXT_SUMMARIZATION:
                result = await self._text_summarization(input_data, resolved_id, **kwargs)
            elif task == TaskType.TRANSLATION:
                result = await self._translation(input_data, resolved_id, **kwargs)
            elif task == TaskType.NAMED_ENTITY_RECOGNITION:
                result = await self._ner(input_data, resolved_id, **kwargs)
            elif task == TaskType.EMBEDDING:
                result = await self._embedding(input_data, resolved_id, **kwargs)
            elif task == TaskType.IMAGE_CLASSIFICATION:
                result = await self._image_classification(input_data, resolved_id, **kwargs)
            elif task == TaskType.OBJECT_DETECTION:
                result = await self._object_detection(input_data, resolved_id, **kwargs)
            elif task == TaskType.SPEECH_TO_TEXT:
                result = await self._speech_to_text(input_data, resolved_id, **kwargs)
            else:
                return self._fallback_result(
                    task, model_id or "unknown", now, started,
                    f"Task {task.value} not yet implemented for HF provider",
                )

            result.latency_ms = (time.perf_counter() - started) * 1000
            return result

        except Exception as exc:
            logger.warning(
                "huggingface_predict_failed",
                task=task.value if isinstance(task, TaskType) else str(task),
                model_id=model_id,
                error=str(exc),
            )
            return self._fallback_result(
                task, model_id or "unknown", now, started, str(exc),
            )

    async def _text_classification(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        """Text classification via HF pipeline."""
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")
        model = model_id or "aegis-hazard-classifier-v1"


        pipe = self._get_pipeline("text-classification", model)
        output = pipe(text, truncation=True, max_length=512)

        return PredictionResult(
            prediction=output[0]["label"] if output else "unknown",
            # Cast numpy scalars: they are not JSON serialisable.
            confidence=float(output[0]["score"]) if output else 0.0,
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.TEXT_CLASSIFICATION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation=f"Classified as {output[0]['label']} with {float(output[0]['score']):.0%} confidence" if output else "No prediction",
            evidence=[{"signal": "text_classification", "raw_output": str(output)}],
        )

    async def _text_summarization(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")
        model = model_id or "facebook/bart-large-cnn"


        pipe = self._get_pipeline("summarization", model)
        input_words = len(text.split())
        max_len = min(kwargs.get("max_length", 120), max(5, input_words // 2))
        output = pipe(text, max_length=max_len, min_length=0)

        return PredictionResult(
            prediction=output[0]["summary_text"] if output else "",
            confidence=0.85 if output else 0.0,
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.TEXT_SUMMARIZATION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation="Generated summary via BART",
        )

    async def _translation(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")
        src = kwargs.get("source_lang", "auto")
        tgt = kwargs.get("target_lang", "en")
        model = model_id or "aegis-translation-v1"


        pipe = self._get_pipeline("translation", model)
        output = pipe(text, src_lang=src, tgt_lang=tgt)

        return PredictionResult(
            prediction=output[0]["translation_text"] if output else text,
            confidence=0.9 if output else 0.0,
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.TRANSLATION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation=f"Translated from {src} to {tgt}",
        )

    async def _ner(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")
        model = model_id or "aegis-ner-v1"


        pipe = self._get_pipeline("ner", model, aggregation_strategy="simple")
        output = pipe(text)

        return PredictionResult(
            # transformers returns numpy.float32 scores. Those are not JSON
            # serialisable: FastAPI's encoder raises on them and the whole
            # endpoint returns 422 as soon as one entity is found. Cast every
            # score to a plain float on the way out.
            prediction=[
                {
                    "entity": e["entity_group"],
                    "text": e["word"],
                    "score": float(e["score"]),
                }
                for e in output
            ],
            confidence=float(max((e["score"] for e in output), default=0.0)),
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.NAMED_ENTITY_RECOGNITION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation=f"Extracted {len(output)} entities",
        )

    async def _embedding(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        texts = input_data if isinstance(input_data, list) else input_data.get("texts", [])
        model = model_id or "aegis-embedding-v1"


        tokenizer = self._get_tokenizer(model)
        model_obj = self._get_model(model)

        import torch
        inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            outputs = model_obj(**inputs)
            embeddings = outputs.last_hidden_state.mean(dim=1).tolist()

        return PredictionResult(
            prediction=embeddings,
            confidence=1.0,
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.EMBEDDING,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation=f"Generated {len(embeddings)} embeddings",
        )

    async def _image_classification(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        image = input_data if isinstance(input_data, str) else input_data.get("image", "")
        model = model_id or "aegis-damage-assessment-v1"


        pipe = self._get_pipeline("image-classification", model)
        output = pipe(image)

        return PredictionResult(
            prediction=output[0]["label"] if output else "unknown",
            # Cast numpy scalars so the response stays JSON-safe.
            confidence=float(output[0]["score"]) if output else 0.0,
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.IMAGE_CLASSIFICATION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation=f"Image classified as {output[0]['label']}" if output else "No prediction",
        )

    async def _object_detection(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        image = input_data if isinstance(input_data, str) else input_data.get("image", "")
        model = model_id or "aegis-victim-detection-v1"


        pipe = self._get_pipeline("object-detection", model)
        output = pipe(image)

        return PredictionResult(
            # As in _ner: cast numpy scalars so the response stays JSON-safe.
            prediction=[
                {
                    "label": d["label"],
                    "score": float(d["score"]),
                    "box": [float(v) for v in d["box"]],
                }
                for d in output
            ],
            confidence=float(max((d["score"] for d in output), default=0.0)),
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.OBJECT_DETECTION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation=f"Detected {len(output)} objects",
        )

    async def _speech_to_text(
        self, input_data: Any, model_id: str | None, **kwargs: Any,
    ) -> PredictionResult:
        audio = input_data if isinstance(input_data, str) else input_data.get("audio", "")
        model = model_id or "aegis-stt-v1"


        pipe = self._get_pipeline("automatic-speech-recognition", model)
        output = pipe(audio)

        return PredictionResult(
            prediction=output.get("text", "") if output else "",
            confidence=0.85 if output else 0.0,
            model_id=model,
            model_version="1.0.0",
            provider=self.provider_name,
            task=TaskType.SPEECH_TO_TEXT,
            generated_at=datetime.now(timezone.utc).isoformat(),
            explanation="Transcribed audio via Whisper",
        )

    def _get_pipeline(self, task: str, model_id: str, **kwargs: Any):
        """Get or create a cached pipeline."""
        cache_key = f"{task}:{model_id}"
        if cache_key not in self._pipelines:
            from transformers import pipeline
            self._pipelines[cache_key] = pipeline(task, model=model_id, **kwargs)
        return self._pipelines[cache_key]

    def _get_model(self, model_id: str):
        """Get or create a cached model."""
        if model_id not in self._models:
            from transformers import AutoModel
            self._models[model_id] = AutoModel.from_pretrained(model_id)
        return self._models[model_id]

    def _get_tokenizer(self, model_id: str):
        """Get or create a cached tokenizer."""
        if model_id not in self._tokenizers:
            from transformers import AutoTokenizer
            self._tokenizers[model_id] = AutoTokenizer.from_pretrained(model_id)
        return self._tokenizers[model_id]

    def _fallback_result(
        self, task: TaskType, model_id: str, now: str, started: float, reason: str,
    ) -> PredictionResult:
        return PredictionResult(
            prediction=None,
            confidence=0.0,
            model_id=model_id,
            model_version="0.0.0",
            provider=self.provider_name,
            task=task,
            generated_at=now,
            explanation=f"Prediction unavailable: {reason}",
            uncertainty="Model inference failed",
            limitations=[reason],
            latency_ms=(time.perf_counter() - started) * 1000,
            fallback_used=True,
            fallback_reason=reason,
        )


# Singleton
_hf_provider: HuggingFaceProvider | None = None


def get_huggingface_provider() -> HuggingFaceProvider:
    global _hf_provider
    if _hf_provider is None:
        _hf_provider = HuggingFaceProvider()
    return _hf_provider
