"""
AI Model Serving Endpoints — exposes AI/ML capabilities to the AEGIS backend.

Endpoints:
    POST /api/ai/analyze-report    — NLP disaster report analysis
    POST /api/ai/analyze-image     — Image analysis pipeline
    POST /api/ai/classify-hazard   — Quick hazard classification
    POST /api/ai/predict           — Model router prediction
    POST /api/ai/forecast          — Time-series forecasting
    POST /api/ai/verify-report     — Report credibility verification
    POST /api/ai/explain           — Explainability
    POST /api/ai/summarize         — Text summarization
    GET  /api/ai/models            — List registered models
    GET  /api/ai/models/{model_id} — Get model details
    GET  /api/ai/providers         — List AI providers
    GET  /api/ai/health            — AI layer health check
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.ai.providers.base import TaskType
from app.ai.router.model_router import get_model_router
from app.ai.registry.model_registry import get_model_registry, register_default_models
from app.ai.nlp.disaster_nlp import get_disaster_nlp
from app.ai.vision.image_analysis import get_image_pipeline
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ── Request/Response Models ──────────────────────────────────────────────


class AnalyzeReportRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    hazard_hint: str | None = None
    preferred_provider: str | None = None


class AnalyzeImageRequest(BaseModel):
    image_base64: str = Field(..., min_length=1)
    image_type: str = Field(default="unknown", pattern="^(satellite|drone|photograph|cctv|unknown)$")
    hazard_context: str | None = None
    lat: float | None = None
    lng: float | None = None
    preferred_provider: str | None = None


class ClassifyHazardRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    hazard_hint: str | None = None
    preferred_provider: str | None = None


class PredictRequest(BaseModel):
    task: str = Field(..., description="Task type (e.g., hazard_classification)")
    input_data: Any = Field(..., description="Input data for the model")
    hazard: str | None = None
    resolution: str | None = None
    preferred_provider: str | None = None
    model_id: str | None = None


class ForecastRequest(BaseModel):
    hazard_type: str = Field(..., description="Hazard type to forecast")
    location: dict[str, Any] = Field(..., description="Location data")
    time_horizon: str = Field(default="24h", pattern="^(\d+h|now)$")
    preferred_provider: str | None = None


class VerifyReportRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    source: str | None = None
    location: dict[str, Any] | None = None


class ExplainRequest(BaseModel):
    prediction_id: str | None = None
    text: str | None = None
    hazard_type: str | None = None
    model_id: str | None = None


class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    max_length: int = Field(default=200, ge=50, le=500)
    preferred_provider: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/analyze-report")
async def analyze_report(
    body: AnalyzeReportRequest,
    _: dict = Depends(get_current_user),
):
    """Full NLP disaster report analysis pipeline."""
    nlp = get_disaster_nlp()
    result = await nlp.analyze(
        body.text,
        hazard=body.hazard_hint,
        preferred_provider=body.preferred_provider,
    )
    return result


@router.post("/analyze-image")
async def analyze_image(
    body: AnalyzeImageRequest,
    _: dict = Depends(get_current_user),
):
    """Full image analysis pipeline."""
    pipeline = get_image_pipeline()
    result = await pipeline.analyze(
        body.image_base64,
        image_type=body.image_type,
        hazard_context=body.hazard_context,
        lat=body.lat,
        lng=body.lng,
        preferred_provider=body.preferred_provider,
    )
    return result


@router.post("/classify-hazard")
async def classify_hazard(
    body: ClassifyHazardRequest,
    _: dict = Depends(get_current_user),
):
    """Quick hazard classification."""
    nlp = get_disaster_nlp()
    result = await nlp.classify(
        body.text,
        hazard=body.hazard_hint,
        preferred_provider=body.preferred_provider,
    )
    return result.to_dict()


@router.post("/predict")
async def predict(
    body: PredictRequest,
    _: dict = Depends(get_current_user),
):
    """Model router prediction — routes to best model/provider."""
    try:
        task = TaskType(body.task)
    except ValueError:
        raise HTTPException(400, detail=f"Unknown task: {body.task}")

    router = get_model_router()
    result = await router.route(
        task,
        body.input_data,
        hazard=body.hazard,
        resolution=body.resolution,
        preferred_provider=body.preferred_provider,
        model_id=body.model_id,
    )
    return result.to_dict()


@router.post("/forecast")
async def forecast(
    body: ForecastRequest,
    _: dict = Depends(get_current_user),
):
    """Time-series forecasting for disaster risk."""
    router = get_model_router()
    result = await router.route(
        TaskType.TIME_SERIES_FORECAST,
        body.location,
        hazard=body.hazard_type,
        preferred_provider=body.preferred_provider,
    )
    return result.to_dict()


@router.post("/verify-report")
async def verify_report(
    body: VerifyReportRequest,
    _: dict = Depends(get_current_user),
):
    """Report credibility verification."""
    nlp = get_disaster_nlp()
    result = await nlp.analyze(body.text)
    return {
        "credibility_score": result.get("credibility_score", 0.0),
        "hazard_type": result.get("hazard_type"),
        "hazard_confidence": result.get("hazard_confidence", 0.0),
        "explanation": result.get("explanation", ""),
        "fallback_used": result.get("fallback_used", True),
    }


@router.post("/explain")
async def explain(
    body: ExplainRequest,
    _: dict = Depends(get_current_user),
):
    """Explainability — generate explanation for a prediction."""
    router = get_model_router()
    result = await router.route(
        TaskType.EXPLAINABILITY,
        body.text or body.prediction_id or "",
        hazard=body.hazard_type,
        model_id=body.model_id,
    )
    return result.to_dict()


@router.post("/summarize")
async def summarize(
    body: SummarizeRequest,
    _: dict = Depends(get_current_user),
):
    """Text summarization."""
    nlp = get_disaster_nlp()
    result = await nlp.summarize(
        body.text,
        preferred_provider=body.preferred_provider,
    )
    return result.to_dict()


@router.get("/models")
async def list_models(
    _: dict = Depends(get_current_user),
):
    """List all registered models."""
    registry = get_model_registry()
    return {"models": registry.snapshot()}


@router.get("/models/{model_id}")
async def get_model(
    model_id: str,
    _: dict = Depends(get_current_user),
):
    """Get model details."""
    registry = get_model_registry()
    entry = registry.get(model_id)
    if not entry:
        raise HTTPException(404, detail=f"Model '{model_id}' not found")
    return registry.snapshot().get(model_id)


@router.get("/providers")
async def list_providers(
    _: dict = Depends(get_current_user),
):
    """List all AI providers and their health."""
    router = get_model_router()
    return await router.health()


@router.get("/health")
async def ai_health(
    _: dict = Depends(get_current_user),
):
    """AI layer health check."""
    router = get_model_router()
    providers = await router.health()
    registry = get_model_registry()

    all_online = all(
        p.get("status") in ("ONLINE", "DEGRADED")
        for p in providers.values()
    )

    return {
        "status": "ok" if all_online else "degraded",
        "providers": providers,
        "models_registered": len(registry.list_all()),
    }
