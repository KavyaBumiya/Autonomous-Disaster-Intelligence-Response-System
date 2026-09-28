from __future__ import annotations

import json
from typing import Any


from app.core.config import get_settings
from app.integrations.base import BaseConnector


class OpenAIConnector(BaseConnector):
    provider = "openai"
    base_url = "https://api.openai.com/v1"
    timeout_seconds = 30.0

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.openai_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = {"type": response_format}
        resp = await self.post(
            "/chat/completions",
            headers=self._headers(),
            json_body=body,
            expect_json=True,
        )
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        return {
            "content": message.get("content", ""),
            "role": message.get("role", "assistant"),
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "finish_reason": choice.get("finish_reason"),
        }

    async def analyze_disaster(
        self,
        context: dict[str, Any],
        analysis_type: str = "situational_awareness",
    ) -> dict[str, Any]:
        prompts = {
            "situational_awareness": "Analyze the following disaster situation and provide a concise situational assessment including key risks, affected areas, and recommended immediate actions.",
            "resource_allocation": "Based on the disaster data below, recommend optimal resource allocation and deployment priorities.",
            "evacuation_planning": "Given the following disaster scenario, provide evacuation planning recommendations including routes, timing, and priority zones.",
            "damage_assessment": "Analyze the disaster data to provide a damage assessment summary with severity estimates and affected infrastructure.",
        }
        system_prompt = prompts.get(analysis_type, prompts["situational_awareness"])
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, indent=2, default=str)},
        ]
        result = await self.chat_completion(
            messages,
            model="gpt-4o-mini",
            temperature=0.2,
            max_tokens=2048,
        )
        return {
            "analysis_type": analysis_type,
            "analysis": result["content"],
            "model": result["model"],
        }
