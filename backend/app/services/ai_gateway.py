"""
AEGIS-AI — AI Gateway
=====================
Implements the AI Gateway layer described in the PRD:

    AI Gateway
    ├── NVIDIA NIM Client       — OpenAI-compatible async HTTP (integrate.api.nvidia.com)
    ├── Model Router            — selects model by task type
    ├── Prompt Manager          — versioned system-prompt templates
    ├── Tool Calling            — structured tool definitions + dispatcher
    ├── Structured Output       — Pydantic schema validation of LLM output
    ├── Retry / Timeout         — connector backoff + circuit breaker
    ├── Fallback Provider       — deterministic DB-query fallback
    └── AI Logging              — structured log of every call + decision

ARCHITECTURE CONSTRAINT (PRD §2 / §6):
  The LLM layer may ONLY understand, summarise, explain, parse, and
  orchestrate tool calls.  It MUST NOT independently assign priority
  scores, allocate resources, or authorise dispatch.  All safety-
  critical decisions flow through the deterministic Decision Engine.

The API key never leaves the backend process.  It is read from
`settings.nvidia_api_key` which is loaded from the server-side .env.
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
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.integrations.ai.nvidia_service import (
    NvidiaNIMConnector,
    extract_json,
    get_nvidia_client,
)

logger = structlog.get_logger()
settings = get_settings()

# ---------------------------------------------------------------------------
# Model Router — maps task types to the right NVIDIA NIM model
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    COMMAND_QUERY    = "command_query"      # Commander natural-language Q&A
    REPORT_PARSE     = "report_parse"       # Citizen-report structured extraction
    SUMMARISE        = "summarise"          # Incident / zone summary
    EXPLAIN          = "explain"            # XAI reasoning explanation
    TRANSLATE        = "translate"          # Multilingual normalisation
    MODERATE         = "moderate"           # Structured content moderation

# NIM exposes one namespaced model id per capability, so every text task routes
# to the same model by default. A caller may still override per call.
_MODEL_ROUTE: dict[TaskType, str] = {
    TaskType.COMMAND_QUERY: settings.nvidia_model,
    TaskType.REPORT_PARSE:  settings.nvidia_model,
    TaskType.SUMMARISE:     settings.nvidia_model,
    TaskType.EXPLAIN:       settings.nvidia_model,
    TaskType.TRANSLATE:     settings.nvidia_model,
    TaskType.MODERATE:      settings.nvidia_model,
}

def route_model(task: TaskType, override: str | None = None) -> str:
    """Return the model name for a task, allowing caller override."""
    return override or _MODEL_ROUTE.get(task, settings.nvidia_model)

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

    "translate_v1": """You are a disaster-response translation assistant for AegisAI.
Translate the user's text into English for the operational pipeline.

Rules:
- Preserve all factual details: numbers, people counts, place names, hazard conditions.
- Keep place names in their original form when an English form is not standard.
- Do not add, infer, or omit information.
- Output ONLY the English translation as plain text — no preamble, no quotes, no markdown.""",

    "moderate_v1": """You are a content-moderation classifier for AegisAI's disaster pipeline.
Classify the message and return ONLY valid JSON (no markdown, no prose):
{
  "flagged": <true|false>,
  "categories": ["<one or more of: personal_data|medical|panic|spam|violence|self_harm|none>"],
  "severity": "<low|medium|high>",
  "reason": "<max 20 words>"
}

Flag a message only when it genuinely risks responder safety, leaks personal
medical data, or is spam/malicious. Ordinary distress reports from affected
people are NOT spam and must never be flagged.""",
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


class TranslationResult(BaseModel):
    """PRD §4-G: canonical English text + preserved original."""
    original_text: str
    translated_text: str
    source_language: str = "en"
    target_language: str = "en"
    was_translated: bool = False
    model_used: str = ""


class CommandQueryResponse(BaseModel):
    response: str
    function_calls: list[dict] = []
    execution_results: list[dict] = []
    execution_time: float = 0.0
    model_used: str = ""
    ai_call_id: str = ""
    ai_used: bool = True
    """
    True only when the NIM model actually produced `response`.

    A configured key is not a working one, so a request that falls back to the
    deterministic reply must report False rather than letting callers infer
    success from `model_used`.
    """


class ModerationVerdict(BaseModel):
    """Structured moderation output (schema-validated like every other task)."""
    flagged: bool = False
    categories: list[str] = []
    severity: str = "low"
    reason: str = ""

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
# The wire format is OpenAI-compatible, so NIM consumes them unchanged.
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
            "name": "get_shelters",
            "description": (
                "List shelters (optionally near a zone or point) with free capacity "
                "and distance. Deterministic — not an LLM estimate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id":     {"type": "string", "description": "Shelters near this zone (optional)"},
                    "lat":         {"type": "number", "description": "Origin latitude (optional)"},
                    "lng":         {"type": "number", "description": "Origin longitude (optional)"},
                    "available_only": {"type": "boolean", "description": "Only shelters with free capacity"},
                    "limit":       {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_route",
            "description": (
                "Compute a disaster-aware route between two points (or from a "
                "team/resource to a zone). Applies flood, traffic, blockage and "
                "weather penalties to cost. Returns deterministic route data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin_lat":    {"type": "number"},
                    "origin_lng":    {"type": "number"},
                    "dest_lat":      {"type": "number"},
                    "dest_lng":      {"type": "number"},
                    "zone_id":       {"type": "string", "description": "Destination zone (overrides dest lat/lng if provided)"},
                    "from_resource_id": {"type": "string", "description": "Origin resource/team ID (optional)"},
                    "blocked_roads": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Known blocked road labels to penalise",
                    },
                },
                "required": [],
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
    # ── Phase 12 additions (11 → 16 tools, PRD §20) ──────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": (
                "Get an hourly weather forecast (Open-Meteo via backend service, "
                "Redis-cached) for a zone or coordinates. Returns source-labelled "
                "data; provider failures degrade honestly instead of fabricating."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {"type": "string", "description": "Zone to resolve coordinates from (optional)"},
                    "lat":     {"type": "number", "description": "Latitude (optional)"},
                    "lng":     {"type": "number", "description": "Longitude (optional)"},
                    "hours":   {"type": "integer", "description": "Forecast hours (default 24)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_earthquakes",
            "description": (
                "List recent earthquakes from USGS (live connector; falls back to "
                "the local USGS poll when the provider is unreachable — degraded "
                "label included). Never fabricated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit":         {"type": "integer", "description": "Max events (default 5)"},
                    "min_magnitude": {"type": "number", "description": "Minimum magnitude (default 0)"},
                    "minutes":       {"type": "integer", "description": "Look-back window in minutes (default 60)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geocode_location",
            "description": (
                "Resolve a free-text place name to coordinates (Nominatim via "
                "backend service, cached). Returns None-shaped result on no match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Place name, e.g. 'Vadodara, Gujarat'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_infrastructure",
            "description": (
                "Query cached GIS infrastructure (OSM via Overpass) near a zone or "
                "point — nearest features of a category, or category counts. "
                "Deterministic PostGIS lookup; empty cache is reported honestly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id":  {"type": "string", "description": "Zone to resolve coordinates from (optional)"},
                    "lat":      {"type": "number"},
                    "lng":      {"type": "number"},
                    "category": {"type": "string", "description": "road|bridge|hospital|clinic|shelter|school|waterway|building (optional)"},
                    "limit":    {"type": "integer", "description": "Max features (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_satellite_evidence",
            "description": (
                "Satellite imagery/evidence for an area. The satellite provider is "
                "NOT configured in this deployment — returns an honest "
                "'provider not configured' response or any cached observations; "
                "it never fabricates imagery (PRD §32)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {"type": "string", "description": "Zone to resolve coordinates from (optional)"},
                    "lat":     {"type": "number"},
                    "lng":     {"type": "number"},
                },
                "required": [],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Core gateway class
# ---------------------------------------------------------------------------

class AIGateway:
    """
    Single entry-point for all LLM calls in AegisAI.

    Usage::

        gateway = AIGateway()
        result  = await gateway.command_query("Why is Zone 17 critical?", db=db)
        parsed  = await gateway.parse_report("There are 5 people trapped near XYZ School")
    """

    def __init__(self) -> None:
        self._connector: NvidiaNIMConnector | None = None

    @property
    def available(self) -> bool:
        """True when NVIDIA_API_KEY is set. No network call is made here."""
        return settings.nvidia_configured

    def _get_connector(self) -> NvidiaNIMConnector:
        if self._connector is None:
            self._connector = get_nvidia_client()
        return self._connector

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
        Process a commander natural-language query via NVIDIA NIM with tool
        calling.

        If no AI provider can answer, returns a fixed statement of
        unavailability with ``ai_used=False``. It never raises, and it never
        returns a canned answer in place of a real one.
        """
        if not self.available:
            return CommandQueryResponse(
                response=_offline_response(user_query),
                model_used="unavailable",
                ai_call_id="unavailable",
                ai_used=False,
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
            logger.warning("nvidia_command_query_failed — AI unavailable", error=str(exc))
            # The key is present but the call did not succeed (bad key, network,
            # rate limit). Report unavailability rather than attributing a
            # canned reply to the NIM model that was attempted.
            return CommandQueryResponse(
                response=_offline_response(user_query),
                model_used="unavailable",
                ai_call_id=log.call_id,
                ai_used=False,
            )

        log.latency_ms = (time.perf_counter() - t_start) * 1000
        _log_call(log)

        return CommandQueryResponse(
            response=response_text,
            function_calls=function_calls_made,
            execution_results=execution_results,
            execution_time=log.latency_ms / 1000,
            model_used=model,
            ai_call_id=log.call_id,
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
                json_mode=True,
            )
            parsed = ParsedReport.model_validate_json(extract_json(raw_json))
        except (ValidationError, json.JSONDecodeError, Exception) as exc:
            log.success = False
            log.error   = str(exc)
            logger.warning("report_parsing_failed", error=str(exc))
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
    # Public: multilingual normalisation (PRD §4-G)
    # ------------------------------------------------------------------

    async def translate(
        self,
        text: str,
        source_language: str = "auto",
    ) -> TranslationResult:
        """
        Normalise citizen / social text into English while preserving the original.

        - English (or unknown-but-likely-English) input is returned unchanged.
        - Non-English input is translated by the AI provider; original_text is
          always kept.
        - On any failure the original text is returned with was_translated=False
          so the ingestion pipeline never blocks on translation.
        """
        if not text or not text.strip():
            return TranslationResult(
                original_text=text or "",
                translated_text=text or "",
                source_language=source_language if source_language != "auto" else "en",
            )

        detected = source_language
        if detected in ("", "auto", None):
            detected = _detect_lang(text)

        # Already English (or undetectable) — no LLM call needed
        if detected in ("en", "unknown"):
            return TranslationResult(
                original_text=text,
                translated_text=text,
                source_language=detected or "en",
                target_language="en",
                was_translated=False,
            )

        if not self.available:
            return TranslationResult(
                original_text=text,
                translated_text=text,
                source_language=detected,
                target_language="en",
                was_translated=False,
            )

        model = route_model(TaskType.TRANSLATE)
        log = AILogRecord(
            task_type=TaskType.TRANSLATE,
            model=model,
            prompt_template="translate_v1",
        )
        t_start = time.perf_counter()

        try:
            translated = await self._simple_call(
                model=model,
                system=get_prompt("translate_v1"),
                user=text,
                temperature=0.0,
                max_tokens=512,
            )
            translated = (translated or "").strip()
            if not translated:
                raise RuntimeError("empty translation")
            was = translated.lower() != text.strip().lower()
            return TranslationResult(
                original_text=text,
                translated_text=translated,
                source_language=detected,
                target_language="en",
                was_translated=was,
                model_used=model,
            )
        except Exception as exc:
            log.success = False
            log.error = str(exc)
            logger.warning("translate_failed", language=detected, error=str(exc))
            return TranslationResult(
                original_text=text,
                translated_text=text,
                source_language=detected,
                target_language="en",
                was_translated=False,
            )
        finally:
            log.latency_ms = (time.perf_counter() - t_start) * 1000
            _log_call(log)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _simple_call(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        """
        Single-turn completion with no tool calling.
        Falls back to `settings.nvidia_fallback_model` when the primary model
        errors (unknown model id, rate limit, upstream 5xx).
        """
        connector = self._get_connector()
        models_to_try = [model]
        fallback = settings.nvidia_fallback_model
        if fallback and fallback != model:
            models_to_try.append(fallback)

        last_exc: Exception | None = None
        for attempt, m in enumerate(models_to_try):
            try:
                result = await connector.chat_completion(
                    [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    model=m,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                content = result.content or ""
                if content.strip():
                    if attempt > 0:
                        logger.info("nvidia_fallback_model_used", model=m, primary=model)
                    return content
                last_exc = RuntimeError(f"empty completion from {m}")
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "nvidia_model_call_failed",
                    model=m,
                    error=str(exc),
                    will_fallback=attempt + 1 < len(models_to_try),
                )
        raise last_exc or RuntimeError("All configured NVIDIA models failed")

    async def _call_with_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: "ToolExecutor | None",
        function_calls_out: list[dict],
        execution_results_out: list[dict],
        log: AILogRecord,
        max_rounds: int | None = None,
    ) -> str:
        """
        Agentic tool-calling loop:
          1. Call the model with tool definitions.
          2. If the model requests tools, execute them via `tool_executor`.
          3. Feed results back and repeat until text response or max_rounds.
        """
        connector      = self._get_connector()
        rounds         = max_rounds or settings.nvidia_max_tool_rounds
        current        = list(messages)

        for _ in range(rounds):
            result = await connector.chat_completion(
                current,
                model=model,
                temperature=0.0,
                max_tokens=1024,
                tools=tools,
                tool_choice="auto",
            )

            log.input_tokens  += result.prompt_tokens
            log.output_tokens += result.completion_tokens

            # ── No tool calls → return text ──────────────────────────
            if not result.tool_calls:
                return result.content or ""

            # ── Execute each tool call ───────────────────────────────
            current.append({
                "role":      "assistant",
                "content":   result.content or None,
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.name,
                            "arguments": tc.raw_arguments or "{}",
                        },
                    }
                    for tc in result.tool_calls
                ],
            })

            for tc in result.tool_calls:
                log.tool_calls_made.append(tc.name)
                function_calls_out.append({"name": tc.name, "arguments": tc.arguments})

                # Execute via the tool executor (if provided)
                if tool_executor is not None:
                    tool_result = await tool_executor.execute(tc.name, tc.arguments)
                else:
                    tool_result = {"error": "No tool executor configured"}

                execution_results_out.append({"function": tc.name, "result": tool_result})

                # Cap tool payload size so multi-round tool use stays inside
                # the model's context budget. Full results remain in
                # execution_results_out for the API response / audit log.
                content = json.dumps(_shrink_tool_result(tool_result), default=str)
                if len(content) > 2500:
                    content = content[:2500] + '…"}'

                current.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         tc.name,
                    "content":      content,
                })

        # Exceeded the round budget — ask for a final text response
        current.append({
            "role":    "user",
            "content": "Please provide a final summary response based on the tool results above.",
        })
        final = await connector.chat_completion(
            current,
            model=model,
            temperature=0.0,
            max_tokens=512,
        )
        return final.content or "Unable to generate response."

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
        from sqlalchemy import select
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

    async def _tool_get_shelters(
        self,
        zone_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        available_only: bool = True,
        limit: int = 5,
    ) -> dict:
        from sqlalchemy import select
        from app.services.route_intelligence import shelters_near
        from app.models.zone import Zone as ZoneModel

        origin_lat, origin_lng = lat, lng
        if zone_id and (lat is None or lng is None):
            z_result = await self.db.execute(
                select(ZoneModel).where(ZoneModel.id == zone_id)
            )
            zone = z_result.scalar_one_or_none()
            if zone:
                origin_lat = zone.centroid_lat
                origin_lng = zone.centroid_lng

        if origin_lat is None or origin_lng is None:
            # Default to all shelters within a wide radius of the first zone
            z2 = await self.db.execute(select(ZoneModel).limit(1))
            zone = z2.scalar_one_or_none()
            if not zone:
                return {"shelters": [], "total": 0, "note": "No origin or zones available"}
            origin_lat, origin_lng = zone.centroid_lat, zone.centroid_lng

        shelters = await shelters_near(
            origin_lat, origin_lng, self.db, limit=limit, radius_km=25.0
        )
        if available_only:
            shelters = [s for s in shelters if s.get("available")]

        return {
            "origin": {"lat": origin_lat, "lng": origin_lng},
            "shelters": shelters,
            "total": len(shelters),
            "note": "Deterministic capacity + distance — no LLM estimation.",
        }

    async def _tool_calculate_route(
        self,
        origin_lat: float | None = None,
        origin_lng: float | None = None,
        dest_lat: float | None = None,
        dest_lng: float | None = None,
        zone_id: str | None = None,
        from_resource_id: str | None = None,
        blocked_roads: list[str] | None = None,
    ) -> dict:
        from sqlalchemy import select
        from app.services.route_intelligence import calculate_route
        from app.models.zone import Zone as ZoneModel
        from app.models.resource import Resource as ResourceModel

        # Resolve destination from zone
        if zone_id and (dest_lat is None or dest_lng is None):
            z_result = await self.db.execute(
                select(ZoneModel).where(ZoneModel.id == zone_id)
            )
            zone = z_result.scalar_one_or_none()
            if zone:
                dest_lat, dest_lng = zone.centroid_lat, zone.centroid_lng

        # Resolve origin from a team/resource
        if from_resource_id and (origin_lat is None or origin_lng is None):
            r_result = await self.db.execute(
                select(ResourceModel).where(ResourceModel.id == from_resource_id)
            )
            res = r_result.scalar_one_or_none()
            if res and res.lat is not None and res.lng is not None:
                origin_lat, origin_lng = res.lat, res.lng

        if None in (origin_lat, origin_lng, dest_lat, dest_lng):
            return {
                "error": (
                    "Need origin_lat/lng and dest_lat/lng (or zone_id / "
                    "from_resource_id to resolve them)."
                )
            }

        route = await calculate_route(
            float(origin_lat),
            float(origin_lng),
            float(dest_lat),
            float(dest_lng),
            blocked_roads=blocked_roads,
            db=self.db,
        )
        route["note"] = route.get("note", "") + " | Deterministic Route Engine — not LLM-generated."
        return route

    async def _tool_generate_explanation(
        self,
        incident_id: str,
        xai_reasoning: str = "",
    ) -> dict:
        gateway     = AIGateway()
        explanation = await gateway.explain_xai(xai_reasoning, incident_id)
        return {
            "incident_id": incident_id,
            "explanation": explanation,
            "source":      "nvidia_xai_explainer",
        }

    # ── Phase 12 additions (PRD §20 — internal services only, no raw DB/HTTP) ──

    async def _resolve_point(
        self, zone_id: str | None, lat: float | None, lng: float | None
    ) -> tuple[float | None, float | None]:
        """Explicit coords win; else resolve zone centroid."""
        if lat is not None and lng is not None:
            return float(lat), float(lng)
        if zone_id:
            from sqlalchemy import select
            from app.models.zone import Zone as ZoneModel

            z = (
                await self.db.execute(select(ZoneModel).where(ZoneModel.id == zone_id))
            ).scalar_one_or_none()
            if z:
                return float(z.centroid_lat), float(z.centroid_lng)
        return None, None

    async def _tool_get_weather_forecast(
        self,
        zone_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        hours: int = 24,
    ) -> dict:
        from app.integrations.base import ConnectorError
        from app.services.weather_service import weather_service

        lat, lng = await self._resolve_point(zone_id, lat, lng)
        if lat is None or lng is None:
            return {"error": "Provide zone_id or lat/lng for the forecast."}
        try:
            forecast = await weather_service.get_forecast(
                lat, lng, hours=min(int(hours), 48), allow_stale=True
            )
        except ConnectorError as exc:
            # Honest degradation — forecast is never invented (§31/§32).
            return {
                "error": f"Weather provider unavailable: {exc.message}",
                "provider": exc.provider,
                "degraded": True,
            }
        payload = forecast.model_dump(mode="json")
        payload.update(
            {
                "provider": weather_service.provider,
                "source": "forecast",
                "note": "Provider data via backend service (Redis-cached) — not LLM-generated.",
            }
        )
        return payload

    async def _tool_get_earthquakes(
        self,
        limit: int = 5,
        min_magnitude: float = 0.0,
        minutes: int = 60,
    ) -> dict:
        from datetime import timedelta

        from sqlalchemy import select
        from app.integrations.base import ConnectorError
        from app.integrations.seismic.usgs import UsgsConnector
        from app.models.seismic import SeismicEvent
        from app.schemas.observations import EarthquakeObservation

        limit = max(1, min(int(limit), 50))
        try:
            fc = await UsgsConnector().recent_events(
                minutes=max(1, int(minutes)),
                min_magnitude=float(min_magnitude),
                limit=limit,
            )
            events = []
            retrieved = datetime.now(timezone.utc)
            for feat in (fc.get("features") or [])[:limit]:
                obs = EarthquakeObservation.from_feature(feat, retrieved_at=retrieved)
                if obs is not None:
                    events.append(obs.model_dump(mode="json"))
            return {
                "source": "usgs/live",
                "provider": "usgs",
                "events": events,
                "total": len(events),
                "note": "Live USGS query — real data, never fabricated.",
            }
        except ConnectorError as exc:
            # Degraded: fall back to the local USGS poller's stored events.
            since = datetime.now(timezone.utc) - timedelta(minutes=int(minutes))
            rows = (
                await self.db.execute(
                    select(SeismicEvent)
                    .where(
                        SeismicEvent.event_time >= since,
                        SeismicEvent.magnitude >= float(min_magnitude),
                    )
                    .order_by(SeismicEvent.event_time.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return {
                "source": "local_usgs_poll_fallback",
                "provider": "usgs",
                "degraded": True,
                "provider_error": exc.message,
                "events": [
                    {
                        "usgs_id": e.usgs_id,
                        "magnitude": e.magnitude,
                        "place": e.place_description,
                        "lat": e.lat,
                        "lng": e.lng,
                        "depth_km": e.depth_km,
                        "event_time": e.event_time.isoformat() if e.event_time else None,
                        "risk_score": e.risk_score,
                    }
                    for e in rows
                ],
                "total": len(rows),
                "note": "Provider unreachable — serving local poller cache (labelled degraded).",
            }

    async def _tool_geocode_location(self, query: str) -> dict:
        from app.services.geocoding import geocode

        if not query or not query.strip():
            return {"error": "Empty query."}
        hit = await geocode(query.strip())
        if not hit:
            return {
                "query": query,
                "result": None,
                "note": "No match (or geocoder unavailable) — nothing invented.",
            }
        return {
            "query": query,
            "result": hit,
            "provider": "nominatim",
            "note": "Geocoded via backend service (cached).",
        }

    async def _tool_get_infrastructure(
        self,
        zone_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> dict:
        from sqlalchemy import and_, func as sa_func, select
        from app.models.infrastructure import Infrastructure
        from app.services.gis_service import bbox_for_radius, nearest_infrastructure

        lat, lng = await self._resolve_point(zone_id, lat, lng)
        if lat is None or lng is None:
            return {"error": "Provide zone_id or lat/lng."}

        if category:
            rows = await nearest_infrastructure(
                self.db, lat, lng, category, limit=max(1, min(int(limit), 50))
            )
            return {
                "source": "cached_osm_gis",
                "category": category,
                "features": rows,
                "total": len(rows),
                "note": "Nearest cached OSM features (PostGIS distance) — deterministic.",
            }

        south, west, north, east = bbox_for_radius(lat, lng, 2000.0)
        counts = (
            await self.db.execute(
                select(Infrastructure.category, sa_func.count(Infrastructure.id))
                .where(
                    and_(
                        Infrastructure.lat.between(south, north),
                        Infrastructure.lng.between(west, east),
                    )
                )
                .group_by(Infrastructure.category)
            )
        ).all()
        by_cat = {str(c): int(n) for c, n in counts}
        if not by_cat:
            return {
                "source": "cached_osm_gis",
                "counts": {},
                "total": 0,
                "note": (
                    "No cached GIS features near this point — cache refresh runs "
                    "in the enrichment pipeline (empty cache reported, never invented)."
                ),
            }
        return {
            "source": "cached_osm_gis",
            "counts": by_cat,
            "total": sum(by_cat.values()),
            "note": "Category counts within 2 km (cached OSM via Overpass).",
        }

    async def _tool_get_satellite_evidence(
        self,
        zone_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
    ) -> dict:
        from sqlalchemy import and_, select
        from app.models.external import ExternalObservation
        from app.services.route_intelligence import SATELLITE_SOURCES

        lat, lng = await self._resolve_point(zone_id, lat, lng)
        rows: list = []
        if lat is not None and lng is not None:
            try:
                from sqlalchemy import or_
                ors = [ExternalObservation.source.ilike(f"{s}%") for s in SATELLITE_SOURCES]
                rows = (
                    await self.db.execute(
                        select(ExternalObservation)
                        .where(
                            and_(
                                or_(*ors),
                                ExternalObservation.lat.between(lat - 0.5, lat + 0.5),
                                ExternalObservation.lng.between(lng - 0.5, lng + 0.5),
                            )
                        )
                        .order_by(ExternalObservation.retrieved_at.desc())
                        .limit(10)
                    )
                ).scalars().all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("satellite_evidence_lookup_failed", error=str(exc))

        if rows:
            return {
                "available": True,
                "source": "cached_satellite_observations",
                "observations": [
                    {
                        "source": r.source,
                        "observation_type": r.observation_type,
                        "lat": r.lat,
                        "lng": r.lng,
                        "value": r.value,
                        "retrieved_at": r.retrieved_at.isoformat()
                        if r.retrieved_at
                        else None,
                    }
                    for r in rows
                ],
                "total": len(rows),
                "note": "Cached observations with provider attribution.",
            }

        return {
            "available": False,
            "provider": "not_configured",
            "observations": [],
            "total": 0,
            "note": (
                "Satellite provider is not configured in this deployment "
                "(no credentials). No imagery available — never fabricated (PRD §32)."
            ),
        }


# ---------------------------------------------------------------------------
# Offline / fallback helpers
# ---------------------------------------------------------------------------

def _shrink_tool_result(result: Any, *, max_str: int = 400, max_list: int = 8) -> Any:
    """
    Recursively shrink a tool result for LLM context.
    Long strings are truncated; long lists are head-sliced.
    Keeps multi-tool command rounds within the model's context budget.
    """
    if isinstance(result, str):
        return result if len(result) <= max_str else result[:max_str] + "…"
    if isinstance(result, dict):
        return {k: _shrink_tool_result(v, max_str=max_str, max_list=max_list)
                for k, v in result.items()}
    if isinstance(result, (list, tuple)):
        head = list(result)[:max_list]
        shrunk = [_shrink_tool_result(v, max_str=max_str, max_list=max_list) for v in head]
        if len(result) > max_list:
            shrunk.append(f"…(+{len(result) - max_list} more)")
        return shrunk
    return result


def _detect_lang(text: str) -> str:
    """Lightweight language detection (langdetect). Falls back to 'en'."""
    try:
        from langdetect import detect, LangDetectException

        try:
            return detect(text[:500])
        except LangDetectException:
            return "en"
    except ImportError:
        return "en"


def _offline_response(query: str) -> str:
    """The single message returned when no AI provider can answer a query.

    There is deliberately no keyword routing here. An earlier version matched
    words like "resource" or "weather" and picked a pre-written paragraph, which
    made a canned string look like a considered answer to a question nobody
    answered. This returns one fixed statement of unavailability instead: it
    performs no analysis, asserts nothing about the incident, and cannot be
    mistaken for a model response. The response is always accompanied by
    ``ai_used=False`` and ``model_used="unavailable"``.

    Live data does not depend on this provider — incidents, resources, zones,
    predictions and the Decision Engine all still work and are served by their
    own endpoints.
    """
    del query  # the message is identical whatever was asked
    return (
        "AI analysis is unavailable: no AI provider is configured or the "
        "provider could not be reached (NVIDIA_API_KEY is unset or the call "
        "failed). No analysis was performed for your question.\n\n"
        "Live provider data is unaffected and still available at: "
        "/api/incidents, /api/resources, /api/zones, "
        "/api/predictions/what-if, /api/command/critical, "
        "/api/command/resources/available."
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
    # §31/§34 — feed the shared provider registry so /api/health can report
    # the AI provider ONLINE/DEGRADED/OFFLINE like every other external connector.
    try:
        from app.integrations import registry as _registry

        if log.success:
            _registry.record_success(
                "nvidia",
                log.latency_ms or 0.0,
                detail={"model": log.model, "task": log.task_type},
            )
        else:
            _registry.record_failure(
                "nvidia", log.error or "AI provider call failed", latency_ms=log.latency_ms or None
            )
    except Exception:  # noqa: BLE001 — registry must never break LLM logging
        pass
    structlog.get_logger().info(
        "nvidia_call",
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

ai_gateway = AIGateway()
