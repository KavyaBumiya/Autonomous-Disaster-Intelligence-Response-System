"""
AEGIS-AI — Groq AI Gateway
===========================
Implements the AI Gateway layer described in the PRD:

    AI Gateway
    ├── Groq Client            — groq SDK, async, with timeout
    ├── Model Router           — selects model by task type and cost
    ├── Prompt Manager         — versioned system-prompt templates
    ├── Tool Calling           — structured tool definitions + dispatcher
    ├── Structured Output      — Pydantic schema validation of LLM output
    ├── Retry / Timeout        — tenacity with exponential back-off
    ├── Fallback Provider      — deterministic DB-query fallback
    └── AI Logging             — structured log of every call + decision

ARCHITECTURE CONSTRAINT (PRD §2 / §6):
  The LLM layer may ONLY understand, summarise, explain, parse, and
  orchestrate tool calls.  It MUST NOT independently assign priority
  scores, allocate resources, or authorise dispatch.  All safety-
  critical decisions flow through the deterministic Decision Engine.

The key never leaves the backend process.  It is read from
`settings.groq_api_key` which is loaded from the server-side .env.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from groq import AsyncGroq
from groq import RateLimitError, APIStatusError, APIConnectionError
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# ---------------------------------------------------------------------------
# Model Router — maps task types to the right Groq model
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    COMMAND_QUERY    = "command_query"      # Commander natural-language Q&A
    REPORT_PARSE     = "report_parse"       # Citizen-report structured extraction
    SUMMARISE        = "summarise"          # Incident / zone summary
    EXPLAIN          = "explain"            # XAI reasoning explanation
    TRANSLATE        = "translate"          # Multilingual normalisation

# Model routing — all mapped to qwen/qwen3.8-27b which is confirmed operational
# on this API key. When upgrading to a key with full model access, restore
# the fast-path split (8B for parsing, 70B for reasoning).
_MODEL_ROUTE: dict[TaskType, str] = {
    TaskType.COMMAND_QUERY:  settings.groq_model,   # qwen/qwen3.8-27b
    TaskType.REPORT_PARSE:   settings.groq_model,   # qwen/qwen3.8-27b (llama-3.1-8b unavailable)
    TaskType.SUMMARISE:      settings.groq_model,
    TaskType.EXPLAIN:        settings.groq_model,
    TaskType.TRANSLATE:      settings.groq_model,
}

def route_model(task: TaskType, override: str | None = None) -> str:
    """Return the model name for a task, allowing caller override."""
    return override or _MODEL_ROUTE.get(task, settings.groq_model)

# ---------------------------------------------------------------------------
# Prompt Manager — versioned system-prompt templates
# ---------------------------------------------------------------------------

_PROMPTS: dict[str, str] = {
    "command_v1": """You are AegisAI Command Center — the AI reasoning layer of an autonomous \
disaster intelligence and response platform.

STRICT CONSTRAINTS:
- You MUST NOT independently assign priority scores, allocate resources, or authorise dispatch.
- All safety-critical numbers and decisions come from the deterministic Decision Engine, \
which you query via tool calls.
- You MAY: understand queries, call tools, summarise evidence, explain decisions, \
suggest next steps, and answer commander questions.
- When you need data, always call the appropriate tool first. \
Never invent incident IDs, zone IDs, or resource counts.
- Label all predictive outputs as "MODEL PROJECTION — subject to human review".

AVAILABLE TOOLS are provided in the tools parameter of each call.
Respond in clear, concise operational English suitable for an incident commander.""",

    "report_parse_v1": """You are a disaster report parser for AegisAI.
Extract structured information from a citizen or field report.

Return ONLY valid JSON matching this schema (no markdown, no prose):
{
  "hazard_type": "<flood|earthquake|fire|cyclone|landslide|unknown>",
  "people_estimated": <integer or null>,
  "condition": "<trapped|injured|missing|safe|unknown>",
  "location_text": "<place name or null>",
  "water_rising": <true|false|null>,
  "structural_damage": <true|false|null>,
  "urgency": "<critical|high|medium|low>",
  "language_detected": "<ISO 639-1 code>",
  "original_text_preserved": "<exact input text>"
}

If a field cannot be determined, use null. Be conservative — do not guess.""",

    "summarise_v1": """You are an incident summariser for AegisAI.
Produce a concise operational summary (max 120 words) for an incident commander.
Use only the evidence data provided. Do not add information not in the evidence.
Format: plain text, no markdown headers.""",

    "explain_xai_v1": """You are an explainability assistant for AegisAI.
Convert the structured XAI evidence provided into a clear, plain-English explanation \
suitable for an incident commander making an approval decision.
Be specific about contributing factors and their weights.
End with the recommended action and its confidence level.
Maximum 200 words.""",
}

def get_prompt(name: str) -> str:
    if name not in _PROMPTS:
        raise KeyError(f"Unknown prompt template: {name!r}")
    return _PROMPTS[name]

# ---------------------------------------------------------------------------
# Structured output schemas (Pydantic)
# ---------------------------------------------------------------------------

class ParsedReport(BaseModel):
    hazard_type: str = "unknown"
    people_estimated: int | None = None
    condition: str = "unknown"
    location_text: str | None = None
    water_rising: bool | None = None
    structural_damage: bool | None = None
    urgency: str = "medium"
    language_detected: str = "en"
    original_text_preserved: str = ""

class CommandQueryResponse(BaseModel):
    response: str
    function_calls: list[dict] = []
    execution_results: list[dict] = []
    execution_time: float = 0.0
    model_used: str = ""
    groq_call_id: str = ""

# ---------------------------------------------------------------------------
# AI Log record
# ---------------------------------------------------------------------------

@dataclass
class AILogRecord:
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str = ""
    model: str = ""
    prompt_template: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    tool_calls_made: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# ---------------------------------------------------------------------------
# Tool definitions — what the LLM can request (PRD §4-C)
# The backend executes these; the model only declares intent.
# ---------------------------------------------------------------------------

COMMAND_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_incidents",
            "description": "List active incidents, optionally filtered by zone or priority threshold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id":   {"type": "string", "description": "Filter by zone ID (optional)"},
                    "threshold": {"type": "number", "description": "Min priority score 0-100 (optional)"},
                    "limit":     {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_incident_details",
            "description": "Get full details, XAI reasoning, and evidence for one incident.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string", "description": "Incident UUID"},
                },
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resources",
            "description": "List available rescue resources. Returns name, type, capacity, location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "available_only": {"type": "boolean", "description": "If true, only show free resources"},
                    "resource_type":  {"type": "string",  "description": "team|vehicle|supply|shelter"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the latest weather reading for a zone (rainfall, wind, risk score).",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {"type": "string"},
                },
                "required": ["zone_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_predictions",
            "description": "Retrieve the latest flood or fire spread prediction for a zone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id":       {"type": "string"},
                    "disaster_type": {"type": "string", "enum": ["flood", "fire"]},
                },
                "required": ["zone_id", "disaster_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_priority",
            "description": (
                "Invoke the deterministic Decision Engine to recalculate priority score "
                "for an incident. Returns score, confidence, and XAI breakdown. "
                "This is the ONLY authoritative source for priority numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string"},
                },
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_simulation",
            "description": (
                "Run a what-if prediction simulation. Results are MODEL PROJECTIONS "
                "and must be labelled as such to the commander."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id":         {"type": "string"},
                    "disaster_type":   {"type": "string", "enum": ["flood", "fire"]},
                    "hours":           {"type": "integer"},
                    "rainfall_mm_hr":  {"type": "number"},
                    "wind_speed_kmh":  {"type": "number"},
                    "resource_delta":  {"type": "integer"},
                },
                "required": ["zone_id", "disaster_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_xai_evidence",
            "description": "Return the structured XAI evidence breakdown for a decision.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string"},
                },
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_explanation",
            "description": "Ask the AI layer to generate a plain-English explanation of an incident's priority and XAI evidence for a commander.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id":    {"type": "string"},
                    "xai_reasoning":  {"type": "string", "description": "Raw XAI string from Decision Engine"},
                },
                "required": ["incident_id"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Retry decorator — wraps every Groq call
# ---------------------------------------------------------------------------

_RETRYABLE = (RateLimitError, APIConnectionError)

def _make_retry():
    return retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, "warning"),  # type: ignore[arg-type]
        reraise=True,
    )

# ---------------------------------------------------------------------------
# Core gateway class
# ---------------------------------------------------------------------------

class GroqGateway:
    """
    Single entry-point for all LLM calls in AegisAI.

    Usage::

        gateway = GroqGateway()
        result  = await gateway.command_query("Why is Zone 17 critical?", db=db)
        parsed  = await gateway.parse_report("There are 5 people trapped near XYZ School")
    """

    def __init__(self) -> None:
        self._key = settings.groq_api_key
        self._client: AsyncGroq | None = None

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _get_client(self) -> AsyncGroq:
        if self._client is None:
            if not self._key:
                raise RuntimeError(
                    "GROQ_API_KEY is not set. Add it to your .env file. "
                    "Never expose this key to the browser."
                )
            self._client = AsyncGroq(api_key=self._key)
        return self._client

    # ------------------------------------------------------------------
    # Public: command query with tool calling
    # ------------------------------------------------------------------

    async def command_query(
        self,
        user_query: str,
        tool_executor: "ToolExecutor | None" = None,
        model_override: str | None = None,
        conversation_history: list[dict] | None = None,
    ) -> CommandQueryResponse:
        """
        Process a commander natural-language query via Groq with tool calling.
        If Groq is unavailable, falls back to deterministic offline responses.
        """
        if not self.available:
            return CommandQueryResponse(
                response=_offline_response(user_query),
                model_used="offline-fallback",
                groq_call_id="offline",
            )

        model   = route_model(TaskType.COMMAND_QUERY, model_override)
        log     = AILogRecord(task_type=TaskType.COMMAND_QUERY, model=model,
                              prompt_template="command_v1")
        t_start = time.perf_counter()

        messages: list[dict] = [
            {"role": "system", "content": get_prompt("command_v1")},
        ]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_query})

        function_calls_made: list[dict] = []
        execution_results:   list[dict] = []

        try:
            response_text = await self._call_with_tools(
                model=model,
                messages=messages,
                tools=COMMAND_TOOLS,
                tool_executor=tool_executor,
                function_calls_out=function_calls_made,
                execution_results_out=execution_results,
                log=log,
            )
        except Exception as exc:
            log.success = False
            log.error   = str(exc)
            _log_call(log)
            logger.warning("Groq call failed — using offline fallback", error=str(exc))
            return CommandQueryResponse(
                response=_offline_response(user_query),
                model_used=model,
                groq_call_id=log.call_id,
            )

        log.latency_ms = (time.perf_counter() - t_start) * 1000
        _log_call(log)

        return CommandQueryResponse(
            response=response_text,
            function_calls=function_calls_made,
            execution_results=execution_results,
            execution_time=log.latency_ms / 1000,
            model_used=model,
            groq_call_id=log.call_id,
        )

    # ------------------------------------------------------------------
    # Public: citizen report structured extraction
    # ------------------------------------------------------------------

    async def parse_report(self, raw_text: str) -> ParsedReport:
        """
        Extract structured fields from a citizen / social-media report.
        Always returns a ParsedReport (falls back to defaults on any error).
        """
        if not self.available or not raw_text.strip():
            return ParsedReport(original_text_preserved=raw_text)

        model   = route_model(TaskType.REPORT_PARSE)
        log     = AILogRecord(task_type=TaskType.REPORT_PARSE, model=model,
                              prompt_template="report_parse_v1")
        t_start = time.perf_counter()

        try:
            raw_json = await self._simple_call(
                model=model,
                system=get_prompt("report_parse_v1"),
                user=raw_text,
                temperature=0.0,
            )
            parsed = ParsedReport.model_validate_json(raw_json)
        except (ValidationError, json.JSONDecodeError, Exception) as exc:
            log.success = False
            log.error   = str(exc)
            logger.warning("Report parsing failed", error=str(exc))
            parsed = ParsedReport(original_text_preserved=raw_text)
        finally:
            log.latency_ms = (time.perf_counter() - t_start) * 1000
            _log_call(log)

        return parsed

    # ------------------------------------------------------------------
    # Public: generate plain-English XAI explanation
    # ------------------------------------------------------------------

    async def explain_xai(self, xai_reasoning: str, incident_id: str) -> str:
        """
        Convert raw XAI evidence string into a commander-readable explanation.
        Returns original reasoning string as fallback.
        """
        if not self.available or not xai_reasoning.strip():
            return xai_reasoning

        model   = route_model(TaskType.EXPLAIN)
        log     = AILogRecord(task_type=TaskType.EXPLAIN, model=model,
                              prompt_template="explain_xai_v1")
        t_start = time.perf_counter()

        prompt_user = (
            f"Incident ID: {incident_id}\n\n"
            f"XAI Evidence:\n{xai_reasoning}"
        )

        try:
            explanation = await self._simple_call(
                model=model,
                system=get_prompt("explain_xai_v1"),
                user=prompt_user,
                temperature=0.2,
            )
        except Exception as exc:
            log.success = False
            log.error   = str(exc)
            explanation = xai_reasoning
        finally:
            log.latency_ms = (time.perf_counter() - t_start) * 1000
            _log_call(log)

        return explanation

    # ------------------------------------------------------------------
    # Public: incident summariser
    # ------------------------------------------------------------------

    async def summarise_incident(self, evidence: dict) -> str:
        """Generate a concise operational summary from structured evidence."""
        if not self.available:
            return _build_fallback_summary(evidence)

        model   = route_model(TaskType.SUMMARISE)
        log     = AILogRecord(task_type=TaskType.SUMMARISE, model=model,
                              prompt_template="summarise_v1")
        t_start = time.perf_counter()

        try:
            summary = await self._simple_call(
                model=model,
                system=get_prompt("summarise_v1"),
                user=json.dumps(evidence, default=str),
                temperature=0.3,
                max_tokens=200,
            )
        except Exception as exc:
            log.success = False
            log.error   = str(exc)
            summary     = _build_fallback_summary(evidence)
        finally:
            log.latency_ms = (time.perf_counter() - t_start) * 1000
            _log_call(log)

        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @_make_retry()
    async def _simple_call(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Single-turn completion with no tool calling."""
        client   = self._get_client()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def _call_with_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: "ToolExecutor | None",
        function_calls_out: list[dict],
        execution_results_out: list[dict],
        log: AILogRecord,
        max_rounds: int = 5,
    ) -> str:
        """
        Agentic tool-calling loop:
          1. Call Groq with tool definitions.
          2. If the model requests tools, execute them via `tool_executor`.
          3. Feed results back and repeat until text response or max_rounds.
        """
        client  = self._get_client()
        current = list(messages)

        for _ in range(max_rounds):
            response = await client.chat.completions.create(
                model=model,
                messages=current,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=1024,
            )

            msg = response.choices[0].message

            # Update token counts for logging
            if response.usage:
                log.input_tokens  += response.usage.prompt_tokens
                log.output_tokens += response.usage.completion_tokens

            # ── No tool calls → return text ──────────────────────────
            if not msg.tool_calls:
                return msg.content or ""

            # ── Execute each tool call ───────────────────────────────
            current.append(msg)  # assistant message with tool_calls

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args: dict = {}
                try:
                    fn_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    fn_args = {}

                log.tool_calls_made.append(fn_name)
                function_calls_out.append({"name": fn_name, "arguments": fn_args})

                # Execute via the tool executor (if provided)
                if tool_executor is not None:
                    result = await tool_executor.execute(fn_name, fn_args)
                else:
                    result = {"error": "No tool executor configured"}

                execution_results_out.append({"function": fn_name, "result": result})

                current.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         fn_name,
                    "content":      json.dumps(result, default=str),
                })

        # Exceeded max rounds — ask for a final text response
        current.append({
            "role":    "user",
            "content": "Please provide a final summary response based on the tool results above.",
        })
        final = await client.chat.completions.create(
            model=model,
            messages=current,
            temperature=0.0,
            max_tokens=512,
        )
        return final.choices[0].message.content or "Unable to generate response."


# ---------------------------------------------------------------------------
# Tool Executor — separates model intent from backend execution
# ---------------------------------------------------------------------------

class ToolExecutor:
    """
    Executes tool calls requested by the LLM against the actual backend.
    The LLM only sees the schema; execution happens here with full DB access.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    async def execute(self, name: str, args: dict) -> dict:
        """Dispatch to the correct backend function."""
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return {"error": f"Unknown tool: {name!r}"}
            return await handler(**args)
        except Exception as exc:
            logger.error("Tool execution error", tool=name, error=str(exc))
            return {"error": str(exc), "tool": name}

    async def _tool_get_incidents(
        self,
        zone_id: str | None = None,
        threshold: float = 0.0,
        limit: int = 5,
    ) -> dict:
        from sqlalchemy import select, and_
        from app.models.incident import Incident

        q = select(Incident).where(
            Incident.active == True,
            Incident.priority_score >= threshold,
        )
        if zone_id:
            q = q.where(Incident.zone_id == zone_id)
        q = q.order_by(Incident.priority_score.desc()).limit(limit)

        result = await self.db.execute(q)
        incidents = result.scalars().all()

        return {
            "incidents": [
                {
                    "id":            inc.id,
                    "zone_id":       inc.zone_id,
                    "disaster_type": inc.disaster_type,
                    "priority_score": inc.priority_score,
                    "status":        inc.status,
                    "victim_count":  inc.victim_count,
                    "report_count":  inc.report_count,
                }
                for inc in incidents
            ],
            "total": len(incidents),
        }

    async def _tool_get_incident_details(self, incident_id: str) -> dict:
        from sqlalchemy import select
        from app.models.incident import Incident

        result = await self.db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        inc = result.scalar_one_or_none()
        if not inc:
            return {"error": "Incident not found", "incident_id": incident_id}

        return {
            "id":              inc.id,
            "zone_id":         inc.zone_id,
            "disaster_type":   inc.disaster_type,
            "priority_score":  inc.priority_score,
            "confidence":      inc.confidence,
            "severity_score":  inc.severity_score,
            "xai_reasoning":   inc.xai_reasoning,
            "victim_count":    inc.victim_count,
            "victim_confidence": inc.victim_confidence,
            "report_count":    inc.report_count,
            "avg_trust_score": inc.avg_trust_score,
            "status":          inc.status,
            "created_at":      inc.created_at.isoformat() if inc.created_at else None,
        }

    async def _tool_get_resources(
        self,
        available_only: bool = True,
        resource_type: str | None = None,
    ) -> dict:
        from sqlalchemy import select, and_
        from app.models.resource import Resource

        filters = []
        if available_only:
            filters.append(Resource.available == True)
            filters.append(Resource.current_load < Resource.capacity)
        if resource_type:
            filters.append(Resource.resource_type == resource_type)

        q = select(Resource)
        if filters:
            q = q.where(and_(*filters))

        result = await self.db.execute(q.order_by(Resource.name))
        resources = result.scalars().all()

        return {
            "resources": [
                {
                    "id":            r.id,
                    "name":          r.name,
                    "resource_type": r.resource_type,
                    "capacity":      r.capacity,
                    "current_load":  r.current_load,
                    "available":     r.available,
                    "lat":           r.lat,
                    "lng":           r.lng,
                }
                for r in resources
            ],
            "total": len(resources),
            "availability_ratio": (
                sum(1 for r in resources if r.available) / len(resources)
                if resources else 0
            ),
        }

    async def _tool_get_weather(self, zone_id: str) -> dict:
        from sqlalchemy import select
        from app.models.weather import WeatherReading
        from datetime import timedelta

        since = datetime.now(timezone.utc) - timedelta(minutes=30)
        result = await self.db.execute(
            select(WeatherReading).where(
                WeatherReading.zone_id == zone_id,
                WeatherReading.polled_at >= since,
            ).order_by(WeatherReading.polled_at.desc()).limit(1)
        )
        w = result.scalar_one_or_none()
        if not w:
            return {"zone_id": zone_id, "data": None, "note": "No recent weather data"}

        return {
            "zone_id":             zone_id,
            "rainfall_mm_hr":      w.rainfall_mm_hr,
            "wind_speed_kmh":      w.wind_speed_kmh,
            "temperature_c":       w.temperature_c,
            "weather_main":        w.weather_main,
            "weather_description": w.weather_description,
            "risk_score":          w.risk_score,
            "polled_at":           w.polled_at.isoformat(),
        }

    async def _tool_get_predictions(self, zone_id: str, disaster_type: str) -> dict:
        from app.engine.prediction_engine import predict_spread
        try:
            result = await predict_spread(zone_id, disaster_type, 12, self.db)
            result["note"] = "MODEL PROJECTION — subject to human review"
            return result
        except Exception as exc:
            return {"error": str(exc), "zone_id": zone_id}

    async def _tool_calculate_priority(self, incident_id: str) -> dict:
        """
        Invoke the DETERMINISTIC Decision Engine.
        The LLM requested this tool; the engine produces the number — not the LLM.
        """
        from sqlalchemy import select
        from app.models.incident import Incident
        from app.engine.decision import score_zone

        result = await self.db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        inc = result.scalar_one_or_none()
        if not inc:
            return {"error": "Incident not found"}

        score = await score_zone(inc.zone_id, inc, self.db)
        return {
            "incident_id":   incident_id,
            "priority_score": score["priority_score"],
            "confidence":     score["confidence"],
            "xai_reasoning":  score["xai_reasoning"],
            "source":         "deterministic_decision_engine",
            "note":           "This score is produced by the rule-based engine, not the LLM.",
        }

    async def _tool_run_simulation(
        self,
        zone_id: str,
        disaster_type: str,
        hours: int = 12,
        rainfall_mm_hr: float = 50.0,
        wind_speed_kmh: float = 20.0,
        resource_delta: int = 0,
    ) -> dict:
        from app.engine.prediction_engine import predict_spread

        try:
            base = await predict_spread(zone_id, disaster_type, hours, self.db)
            adjusted_priority = max(
                0.0, min(100.0, base.get("priority_base", 50.0) + resource_delta * 3.0)
            )
            return {
                **base,
                "adjusted_priority": adjusted_priority,
                "resource_delta":    resource_delta,
                "note":              "MODEL PROJECTION — subject to human review",
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _tool_get_xai_evidence(self, incident_id: str) -> dict:
        from sqlalchemy import select
        from app.models.incident import Incident

        result = await self.db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        inc = result.scalar_one_or_none()
        if not inc:
            return {"error": "Incident not found"}

        return {
            "incident_id":    incident_id,
            "priority_score": inc.priority_score,
            "xai_reasoning":  inc.xai_reasoning,
            "confidence":     inc.confidence,
            "severity_score": inc.severity_score,
            "report_count":   inc.report_count,
            "avg_trust":      inc.avg_trust_score,
            "victim_count":   inc.victim_count,
            "disaster_type":  inc.disaster_type,
        }

    async def _tool_generate_explanation(
        self,
        incident_id: str,
        xai_reasoning: str = "",
    ) -> dict:
        gateway     = GroqGateway()
        explanation = await gateway.explain_xai(xai_reasoning, incident_id)
        return {
            "incident_id": incident_id,
            "explanation": explanation,
            "source":      "groq_xai_explainer",
        }


# ---------------------------------------------------------------------------
# Offline / fallback helpers
# ---------------------------------------------------------------------------

def _offline_response(query: str) -> str:
    """Rule-based offline responses when Groq is unavailable."""
    q = query.lower()

    if any(w in q for w in ("critical", "urgent", "highest priority")):
        return (
            "⚠️  Groq AI is offline. Using deterministic fallback.\n"
            "To see critical incidents: check the live incidents panel or call "
            "GET /api/command/critical directly."
        )
    if any(w in q for w in ("resource", "team", "available")):
        return (
            "⚠️  Groq AI is offline. Resource data: "
            "call GET /api/command/resources/available for live resource status."
        )
    if any(w in q for w in ("predict", "flood", "fire", "spread", "simulation")):
        return (
            "⚠️  Groq AI is offline. Prediction simulations are available at "
            "POST /api/predictions/what-if with zone_id and disaster_type."
        )
    if any(w in q for w in ("weather", "rain", "wind")):
        return (
            "⚠️  Groq AI is offline. Weather data is polled every 5 minutes "
            "from Open-Meteo. Check the zone detail panel."
        )

    return (
        "⚠️  Groq AI Gateway is currently offline (GROQ_API_KEY not set or service unavailable).\n"
        "The deterministic Decision Engine and all data APIs are still operational.\n"
        "Available endpoints: /api/incidents, /api/resources, /api/zones, "
        "/api/predictions/what-if, /api/command/critical"
    )

def _build_fallback_summary(evidence: dict) -> str:
    parts = []
    if evidence.get("disaster_type"):
        parts.append(f"Type: {evidence['disaster_type'].upper()}")
    if evidence.get("priority_score") is not None:
        parts.append(f"Priority: {evidence['priority_score']}/100")
    if evidence.get("victim_count"):
        parts.append(f"Estimated victims: {evidence['victim_count']}")
    if evidence.get("report_count"):
        parts.append(f"Reports: {evidence['report_count']}")
    return " | ".join(parts) if parts else "No summary data available."

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------

def _log_call(log: AILogRecord) -> None:
    structlog.get_logger().info(
        "groq_call",
        call_id=log.call_id,
        task=log.task_type,
        model=log.model,
        latency_ms=round(log.latency_ms, 1),
        tokens_in=log.input_tokens,
        tokens_out=log.output_tokens,
        tools=log.tool_calls_made,
        success=log.success,
        error=log.error,
    )

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

groq_gateway = GroqGateway()
