from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.integrations.ai.openai_service import OpenAIConnector
from app.integrations.base import ConnectorError

router = APIRouter()


class DisasterAnalysisRequest(BaseModel):
    context: dict = Field(default_factory=dict)
    analysis_type: str = Field(
        default="situational_awareness",
        pattern="^(situational_awareness|resource_allocation|evacuation_planning|damage_assessment)$",
    )


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 1024


@router.post("/analyze-disaster", tags=["openai"])
async def analyze_disaster(
    body: DisasterAnalysisRequest,
    _: dict = Depends(get_current_user),
):
    connector = OpenAIConnector()
    try:
        result = await connector.analyze_disaster(body.context, body.analysis_type)
        return {"provider": "openai", **result}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.post("/chat", tags=["openai"])
async def chat(
    body: ChatRequest,
    _: dict = Depends(get_current_user),
):
    connector = OpenAIConnector()
    try:
        result = await connector.chat_completion(
            body.messages,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        return {"provider": "openai", **result}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc
