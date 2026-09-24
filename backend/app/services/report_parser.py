"""
AEGIS-AI — Groq-powered Citizen Report Parser
==============================================
Converts raw text/voice-transcript into a structured ParsedReport
that the ingestion pipeline can act on immediately.

Architecture (PRD §4-B):
  raw text → Groq (parse_report) → ParsedReport (structured)
                                 ↓
               NLP service (disaster_type, trust scoring, geocoding)
                                 ↓
               Orchestrator (zone upsert, incident creation, Decision Engine)

The LLM only extracts structured intent from text.
Disaster classification and priority scoring remain deterministic.
"""
from __future__ import annotations

import structlog

from app.services.groq_gateway import groq_gateway, ParsedReport

logger = structlog.get_logger()


async def parse_citizen_report(raw_text: str) -> ParsedReport:
    """
    Parse a citizen report into structured fields using Groq.

    Returns a ParsedReport with best-effort extraction.
    Falls back to defaults if Groq is unavailable or text is empty.

    Example input:
        "There are 5 people trapped near XYZ School. The water is rising fast."

    Example output::

        ParsedReport(
            hazard_type="flood",
            people_estimated=5,
            condition="trapped",
            location_text="XYZ School",
            water_rising=True,
            urgency="critical",
            language_detected="en",
            original_text_preserved="There are 5 people..."
        )
    """
    if not raw_text or not raw_text.strip():
        return ParsedReport(original_text_preserved=raw_text or "")

    parsed = await groq_gateway.parse_report(raw_text)
    logger.info(
        "report_parsed",
        hazard=parsed.hazard_type,
        urgency=parsed.urgency,
        people=parsed.people_estimated,
        location=parsed.location_text,
        groq_available=groq_gateway.available,
    )
    return parsed


def parsed_report_to_nlp_hints(parsed: ParsedReport) -> dict:
    """
    Convert a ParsedReport into hints that supplement the NLP pipeline.
    This avoids double-calling the LLM when the Orchestrator enriches the report.
    """
    return {
        "disaster_type":     parsed.hazard_type if parsed.hazard_type != "unknown" else None,
        "people_estimated":  parsed.people_estimated,
        "location_text":     parsed.location_text,
        "urgency":           parsed.urgency,
        "language_detected": parsed.language_detected,
        "structural_damage": parsed.structural_damage,
        "water_rising":      parsed.water_rising,
    }
