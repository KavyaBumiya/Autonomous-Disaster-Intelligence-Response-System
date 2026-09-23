"""
LLM Orchestration for Command Center — Function-calling enabled LLM layer.

This module provides an LLM (Claude/GPT via API) interface with tool use / function
calling to query the AegisAI decision engine and return structured, explainable answers
in natural language for the Command Center dashboard.

Supports:
- Natural language queries about incidents, weather, predictions
- Function calling to fetch real data from the engine
- Multi-turn conversation with context tracking
- Fallback to rule-based responses if LLM API unavailable
"""
import json
import structlog
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


# ── Tool Definitions (what the LLM can call) ─────────────────────────────

# These are the functions the LLM can call via function calling API

TOOL_DEFINITIONS = [
    {
        "name": "get_incident_status",
        "description": "Get the current status of an incident by ID, including disaster type, severity, and latest updates.",
        "parameters": {
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "The incident/report ID to look up"}
            },
            "required": ["incident_id"]
        }
    },
    {
        "name": "get_zone_weather",
        "description": "Get current weather conditions and risk score for a zone centroid.",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "The zone ID to get weather for"},
                "centroid_lat": {"type": "number", "description": "Zone centroid latitude"},
                "centroid_lng": {"type": "number", "description": "Zone centroid longitude"}
            },
            "required": ["zone_id"]
        }
    },
    {
        "name": "get_prediction_update",
        "description": "Get flood or fire spread prediction for a zone over the next hours.",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "The zone ID"},
                "prediction_type": {"type": "string", "enum": ["flood", "fire"], "description": "Type of prediction"},
                "hours: number": {"type": "number", "description": "Forecast horizon in hours"}
            },
            "required": ["zone_id", "prediction_type"]
        }
    },
    {
        "name": "get_trust_score",
        "description": "Get the trust/fake-report score for a specific report ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "report_id": {"type": "string", "description": "The report/reading ID to check"}
            },
            "required": ["report_id"]
        }
    },
    {
        "name": "search_reports",
        "description": "Search reports by disaster type, location, or keyword matching.",
        "parameters": {
            "type": "object",
            "properties": {
                "disaster_type": {"type": "string", "enum": ["flood", "fire", "earthquake", "cyclone"], "description": "Filter by disaster type"},
                "location_lat": {"type": "number", "description": "Filter by latitude proximity"},
                "location_lng": {"type": "number", "description": "Filter by longitude proximity"},
                "keyword": {"type": "string", "description": "Keyword search in report text"},
                "limit": {"type": "integer", "description": "Maximum results to return", "default": 10}
            },
            "required": []
        }
    }
]


# ── LLM Query Function ──────────────────────────────────────────────────

async def query_llm(
    user_query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    available_tools: Optional[Sequence[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Send a natural language query to an LLM with function calling capability.
    
    Args:
        user_query: The natural language question/request from the user
        conversation_history: Optional list of {role: "user"/"assistant", content: "..."} messages
        available_tools: Optional list of tool definitions the LLM can call
    
    Returns:
        Dict with LLM response containing either:
        - "text": natural language response, or
        - "tool_calls": list of function calls to execute, or
        - both (text + suggested tool calls)
    """
    # Use available tools or default to our tool definitions
    tools = available_tools or TOOL_DEFINITIONS
    
    # In production, this would call Claude API (anthropic) or OpenAI with function calling
    # For now, we implement a rule-based fallback that handles common query patterns
    
    response = await _handle_query_with_fallback(user_query, conversation_history, tools)
    return response


async def _handle_query_with_fallback(
    user_query: str,
    conversation_history: Optional[List[Dict[str, str]]],
    tools: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Rule-based fallback for LLM queries when API is unavailable.
    Handles common Command Center query patterns.
    """
    query_lower = user_query.lower().strip()
    
    # Pattern: "What's the status of incident X?"
    if "status" in query_lower and "incident" in query_lower:
        incident_id = _extract_incident_id(user_query)
        if incident_id:
            # Would call get_incident_status tool
            return {
                "text": f"Fetching status for incident {incident_id}... (would use tool call in production)",
                "tool_calls": [{"name": "get_incident_status", "arguments": {"incident_id": incident_id}}]
            }
    
    # Pattern: "What's the weather like in zone X?"
    if "weather" in query_lower and "zone" in query_lower:
        zone_id = _extract_zone_id(user_query)
        if zone_id:
            return {
                "text": f"Fetching weather for zone {zone_id}... (would use tool call in production)",
                "tool_calls": [{"name": "get_zone_weather", "arguments": {"zone_id": zone_id}}]
            }
    
    # Pattern: "Will there be flooding in zone X?"
    if "flood" in query_lower or "flooding" in query_lower:
        # Try to extract zone info
        import re
        zone_match = re.search(r'(?:zone|area)\s+([a-z0-9_]+)', user_query, re.IGNORECASE)
        zone_id = zone_match.group(1) if zone_match else None
        
        if zone_id:
            return {
                "text": f"Checking flood prediction for zone {zone_id}... (would use prediction tool in production)",
                "tool_calls": [{"name": "get_prediction_update", "arguments": {"zone_id": zone_id, "prediction_type": "flood"}}]
            }
    
    # Pattern: "Is this report reliable? / trust score for X"
    if "trust" in query_lower or "reliable" in query_lower or "score" in query_lower:
        import re
        report_match = re.search(r'(?:report|reading)\s+([a-f0-9-]+)', user_query, re.IGNORECASE)
        report_id = report_match.group(1) if report_match else None
        
        if report_id:
            return {
                "text": f"Checking trust score for report {report_id}... (would use trust scoring tool in production)",
                "tool_calls": [{"name": "get_trust_score", "arguments": {"report_id": report_id}}]
            }
    
    # Pattern: "Find reports about X in area Y"
    if "find" in query_lower or "search" in query_lower:
        keyword = None
        location_match = re.search(r'(?:near|at|around)\s+([\d.-]+)\s*,\s*([\d.-]+)', user_query)
        if location_match:
            lat, lng = float(location_match.group(1)), float(location_match.group(2))
            keyword = user_query
        
        return {
            "text": f"Searching reports for: {user_query[:100]}... (would use search_reports tool in production)",
            "tool_calls": [{"name": "search_reports", "arguments": {"keyword": user_query[:100], "limit": 10}}]
        }
    
    # Default: general response
    return {
        "text": (
            "I'm your AegisAI Command Center assistant. I can help you with:\n"
            "• Incident status and details\n"
            "• Weather conditions for zones\n"
            "• Flood/fire spread predictions\n"
            "• Report trust/fake-score assessment\n"
            "• Search reports by keyword or location\n\n"
            "Please ask me a specific question, and I'll fetch the latest data from our "
            "decision engine for you."
        )
    }


# ── Query Helper Functions ──────────────────────────────────────────────

def _extract_incident_id(query: str) -> Optional[str]:
    """Extract incident ID from natural language query."""
    import re
    match = re.search(r'incident\s+([a-f0-9-]+)', query, re.IGNORECASE)
    if match:
        return match.group(1)
    # Try GUID pattern
    match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', query)
    return match.group(0) if match else None


def _extract_zone_id(query: str) -> Optional[str]:
    """Extract zone ID from natural language query."""
    import re
    match = re.search(r'zone\s+([a-z0-9_]+)', query, re.IGNORECASE)
    if match:
        return match.group(1)
    # Try common zone naming patterns
    match = re.search(r'(?:zone|area)_?(\d+)', query, re.IGNORECASE)
    return match.group(1) if match else None