"""Command Center API — Ollama LLM integration.
Handles natural language queries with function calling to the Decision Engine.
Supports both online mode (Ollama LLM) and offline demo mode.
"""
from datetime import datetime, timezone
import json
import httpx
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.models.incident import Incident
from app.models.resource import Resource
from app.models.zone import Zone
from app.engine.decision import score_zone
from app.services.websocket import emit_command_interaction, emit_incident_priority_updated
from app.services.deduplication import deduplicate_reports

router = APIRouter(prefix="/api/command", tags=["command center"])

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


@router.get("/health")
async def command_health():
    """Check if Ollama LLM is available."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            return {"available": resp.status_code == 200, "model": DEFAULT_MODEL}
    except Exception:
        return {"available": False}

# ─── Request / Response Models ───────────────────────────────────────────

class CommandQueryRequest(BaseModel):
    user_query: str = Field(..., description="User's natural language query")
    model_name: str | None = Field(None, description="Override default model (llama3.2/phi3)")
    conversation_id: str | None = Field(None, description="Optional conversation ID for multi-turn")


class FunctionCall(BaseModel):
    name: str
    arguments: dict


class CommandResponse(BaseModel):
    response: str
    function_calls: list[FunctionCall] = []
    execution_results: list[dict] = []
    execution_time: float
    model_used: str


# ─── System Prompt with Function Definitions ──────────────────────────────

YOUR_SYSTEM_PROMPT = """You are AegisAI Command Center — an AI assistant for disaster response operations.

You have access to the following functions to help manage disaster response:

## Available Functions:

### 1. get_incident_priority(incident_id: str)
- **What it does**: Returns priority score and XAI reasoning for an incident
- **When to use**: User asks "How urgent is this incident?" or "What's the priority?"
- **Returns**: 
  - priority_score (0-100)
  - confidence (0.0-1.0) 
  - xai_reasoning (text explanation)
  - victim_count, victim_confidence (if available)
  - disaster_type, zone_id

### 2. assign_resources(incident_id: str, resource_count: int)
- **What it does**: Assigns available resources to an incident
- **When to use**: User says "Deploy teams", "Assign resources", "Send help"
- **Parameters**:
  - incident_id: The incident to assign to
  - resource_count: Number of resources to assign (1-10 recommended)
- **Returns**:
  - action_id (for commander approval)
  - assigned_resources list (name, type, capacity)
  - updated_priority_score
  - message confirming assignment

### 3. run_prediction(zone_id: str, disaster_type: str, hours: int, rainfall_mm_hr: float = 50.0, wind_speed_kmh: float = 20.0)
- **What it does**: Runs flood or fire spread simulation
- **When to use**: User asks "Will flood spread?" or "How fire will propagate?"
- **Parameters**:
  - zone_id: Target zone
  - disaster_type: "flood" or "fire"
  - hours: Simulation hours (1-24 recommended)
  - rainfall_mm_hr: For flood (default 50)
  - wind_speed_kmh: For fire (default 20)
- **Returns**:
  - affected_cells / burned_area (list of {lat, lng, intensity, time_step})
  - max_intensity (0-100)
  - flooded_percentage / burned_area_percentage
  - expires_at (timestamp)

### 4. list_available_resources() 
- **What it does**: Lists all resources currently available (available=True, current_load < capacity)
- **When to use**: User asks "How many teams do we have?" or "What resources are free?"
- **Returns**:
  - resources list (id, name, type, capacity, current_load, lat/lng)
  - availability ratio
  - suggestion on allocation

### 5. get_zone_status(zone_id: str)
- **What it does**: Comprehensive zone overview
- **When to use**: User asks "Tell me about zone X" or "What's happening in [area]?"
- **Returns**:
  - zone details (name, centroid, radius)
  - incident (priority, status, victim count)
  - available resources count
  - last prediction results
  - recent reports count

### 6. get_critical_incidents(threshold: float = 70.0)
- **What it does**: Lists incidents above priority threshold
- **When to use**: User asks "Which incidents are most urgent?" or "Show me high-priority situations"
- **Parameters**:
  - threshold: Priority threshold (0-100, default 70)
- **Returns**:
  - list of incidents above threshold, each with:
    - incident_id, priority_score, disaster_type, victim_count
    - zone_id, xai_reasoning summary
    - recommended action

### 7. get_incident_reports(incident_id: str, limit: int = 10)
- **What it does**: Lists recent reports for an incident
- **When to use**: User asks "What reports are for this incident?" or "What triggered this?"
- **Parameters**:
  - incident_id: The incident
  - limit: Max reports to return (default 10)
- **Returns**:
  - reports list (id, source, trust_score, disaster_type, message_text excerpt)
  - timestamps, whether suppressed"""


# ─── Helper: Execute Function ────────────────────────────────────────────

async def execute_function(func_name: str, func_args: dict, db: AsyncSession) -> dict:
    """Execute the mapped function and return result dict."""
    
    if func_name == "get_incident_priority":
        incident_id = func_args.get("incident_id")
        if not incident_id:
            return {"error": "incident_id required"}
        from app.models.incident import Incident
        result = await db.execute(select(Incident).where(Incident.id == incident_id))
        incident = result.scalar_one_or_none()
        if not incident:
            return {"error": "Incident not found"}
        # Pass the incident object, not just the ID
        from app.engine.decision import score_zone
        score_result = await score_zone(incident.zone_id, incident, db)
        return {
            "priority_score": score_result.get("priority_score", 0),
            "confidence": score_result.get("confidence", 0),
            "xai_reasoning": score_result.get("xai_reasoning", "No reasoning available"),
        }

    elif func_name == "assign_resources":
         incident_id = func_args.get("incident_id")
         resource_count = func_args.get("resource_count", 1)
         if not incident_id:
             return {"error": "incident_id required"}
         from app.models.incident import Incident
         result = await db.execute(select(Incident).where(Incident.id == incident_id))
         incident = result.scalar_one_or_none()
         if not incident:
             return {"error": "Incident not found"}
         # Run the resource commander with the loaded incident
         from app.engine.resource_commander import command_resources
         result = await command_resources(incident, db)
         return {
             "action_id": result.get("action_id", ""),
             "assigned_resources": result.get("assigned_resources", []),
             "priority_score": result.get("priority_score", incident.priority_score or 0.0),
         }
    
    elif func_name == "run_prediction":
        zone_id = func_args.get("zone_id")
        disaster_type = func_args.get("disaster_type", "flood")
        hours = func_args.get("hours", 12)
        rainfall = func_args.get("rainfall_mm_hr", 50.0)
        wind_speed = func_args.get("wind_speed_kmh", 20.0)
        # Call prediction engine
        from app.engine.prediction_engine import predict_spread
        result = await predict_spread(zone_id, disaster_type, hours, db)
        return result
    
    elif func_name == "list_available_resources":
        result = await db.execute(
            select(Resource).where(
                and_(Resource.available == True, Resource.current_load < Resource.capacity)
            )
        )
        resources = result.scalars().all()
        return {
            "resources": [
                {
                    "id": r.id,
                    "name": r.name,
                    "resource_type": r.resource_type,
                    "capacity": r.capacity,
                    "current_load": r.current_load,
                    "available": r.available,
                    "lat": r.lat,
                    "lng": r.lng,
                }
                for r in resources
            ]
        }
    
    elif func_name == "get_zone_status":
        zone_id = func_args.get("zone_id")
        if not zone_id:
            return {"error": "zone_id required"}
        # Get zone + incident + resources summary
        zone_result = await db.execute(select(Zone).where(Zone.id == zone_id))
        zone = zone_result.scalar_one_or_none()
        incident_result = await db.execute(
            select(Incident).where(Incident.zone_id == zone_id, Incident.active == True).limit(1)
        )
        incident = incident_result.scalar_one_or_none()
        resources_result = await db.execute(
            select(Resource).where(
                and_(Resource.available == True, Resource.current_load < Resource.capacity)
            )
        )
        resources = resources_result.scalars().all()
        # Build summary
        return {
            "zone_id": zone_id,
            "zone_name": zone.name if zone else None,
            "incident": {
                "id": incident.id if incident else None,
                "priority_score": incident.priority_score if incident else 0,
                "disaster_type": incident.disaster_type if incident else None,
                "victim_count": incident.victim_count if incident else 0,
                "status": incident.status if incident else "active",
            } if incident else None,
            "available_resources": len(resources),
            "recent_reports": 0,  # simplified
        }
    
    elif func_name == "get_critical_incidents":
        threshold = func_args.get("threshold", 70.0)
        result = await db.execute(
            select(Incident).where(Incident.priority_score >= threshold, Incident.active == True)
        )
        incidents = result.scalars().all()
        return {
            "incidents": [
                {
                    "incident_id": inc.id,
                    "priority_score": inc.priority_score,
                    "disaster_type": inc.disaster_type,
                    "victim_count": inc.victim_count or 0,
                    "zone_id": inc.zone_id,
                    "recommended_action": "Deploy resources" if inc.priority_score >= 80 else "Monitor",
                }
                for inc in incidents
            ]
        }
    
    elif func_name == "get_incident_reports":
        incident_id = func_args.get("incident_id")
        limit = func_args.get("limit", 10)
        if not incident_id:
            return {"error": "incident_id required"}
        result = await db.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        incident = result.scalar_one_or_none()
        # Return recent reports - simplified, would query actual reports table
        return {
            "reports": [
                {
                    "id": r.id,
                    "source": r.source,
                    "trust_score": r.trust_score,
                    "disaster_type": r.disaster_type,
                    "excerpt": (r.message_text or r.transcript or "")[:80] if (r.message_text or r.transcript) else "",
                    "timestamp": r.created_at.isoformat() if r.created_at else None,
                }
                for r in []  # placeholder - would query reports
            ],
            "total": 0,
        }
    
    else:
        return {"error": f"Unknown function: {func_name}"}


# ─── API Endpoint ────────────────────────────────────────────────────────

@router.post("/query", response_model=CommandResponse)
async def command_query(
    request: CommandQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["commander"])),
):
    """Process LLM command query with function calling via Ollama."""
    start_time = datetime.now(timezone.utc)
    
    # Check if Ollama is available
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get("http://localhost:11434/api/tags")
            ollama_available = health.status_code == 200
    except Exception:
        ollama_available = False
    
    # Build messages with system prompt
    system_prompt = YOUR_SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request.user_query},
    ]
    
    # If Ollama not available, fall back to direct database queries
    if not ollama_available:
        return await _offline_fallback(request.user_query, db)
    
    # Call Ollama
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://localhost:11434/api/chat",
            json={
                "model": request.model_name or DEFAULT_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0},  # Deterministic for consistency
            },
        )
    
    if resp.status_code != 200:
        raise HTTPException(502, "Ollama API error")
    
    ollama_response = resp.json()
    execution_time = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    # Check for function call in response
    function_calls = []
    execution_results = []
    
    if "message" in ollama_response:
        msg = ollama_response["message"]
        
        # Check for function call
        if "function_call" in msg:
            fc = msg["function_call"]
            func_name = fc["name"]
            func_args = json.loads(fc["arguments"])
            
            # Execute the function
            result = await execute_function(func_name, func_args, db)
            execution_results.append({"function": func_name, "result": result})
            
            # Add function message to conversation context
            # (In full implementation, would re-send with function result)
            
            function_calls.append(FunctionCall(name=func_name, arguments=func_args))
    
    # Parse the assistant's response text
    assistant_message = ""
    if "message" in ollama_response and "content" in ollama_response["message"]:
        assistant_message = ollama_response["message"]["content"]
    
    return CommandResponse(
        response=assistant_message,
        function_calls=function_calls,
        execution_results=execution_results,
        execution_time=execution_time,
        model_used=request.model_name or DEFAULT_MODEL,
    )


# ─── Offline Demo Fallback ─────────────────────────────────────────────

async def _offline_fallback(user_query: str, db: AsyncSession) -> CommandResponse:
    """Fallback when Ollama is not available — use direct database queries."""
    start_time = datetime.now(timezone.utc)
    
    query_lower = user_query.lower()
    
    # Try to interpret the query and provide a direct response
    if "priority" in query_lower and "incident" in query_lower:
        # Try to get an incident's priority
        result = await db.execute(select(Incident).limit(1))
        incident = result.scalar_one_or_none()
        if incident:
            return CommandResponse(
                response=f"Incident {incident.id} has priority score {incident.priority_score}/100 with XAI reasoning: {incident.xai_reasoning or 'N/A'}",
                execution_time=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )
    
    # Try critical incidents
    if "critical" in query_lower:
        result = await db.execute(
            select(Incident).where(Incident.priority_score >= 70, Incident.active == True).limit(3)
        )
        incidents = result.scalars().all()
        if incidents:
            lines = []
            for inc in incidents:
                lines.append(f"- Incident {inc.id}: priority {inc.priority_score}/100, type {inc.disaster_type or 'unknown'}, victims: {inc.victim_count or 0}")
            return CommandResponse(
                response=f"Critical incidents (priority ≥70):\n" + "\n".join(lines),
                execution_time=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )
    
    # Default response
    return CommandResponse(
        response="I'm unable to connect to the LLM service. Showing basic system information. Would you like me to check critical incidents, incident priorities, or available resources?",
        execution_time=(datetime.now(timezone.utc) - start_time).total_seconds(),
    )


# ─── NEW: list_available_resources ────────────────────────────────────
@router.get("/resources/available")
async def list_available_resources_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["commander", "responder"])),
):
    """Lists all resources currently available (available=True, current_load < capacity)."""
    result = await db.execute(
        select(Resource).where(
            and_(Resource.available == True, Resource.current_load < Resource.capacity)
        )
    )
    resources = result.scalars().all()
    return {
        "resources": [
            {
                "id": r.id,
                "name": r.name,
                "resource_type": r.resource_type,
                "capacity": r.capacity,
                "current_load": r.current_load,
                "available": r.available,
                "lat": r.lat,
                "lng": r.lng,
            }
            for r in resources
        ]
    }

# ─── NEW: zone_status ────────────────────────────────────────────────
@router.get("/zone-status")
async def zone_status_endpoint(
    zone_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["commander", "responder"])),
):
    """Comprehensive zone overview."""
    from sqlalchemy import select, func, and_

    zone_result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = zone_result.scalar_one_or_none()
    incident_result = await db.execute(
        select(Incident).where(Incident.zone_id == zone_id, Incident.active == True).limit(1)
    )
    incident = incident_result.scalar_one_or_none()
    resources_result = await db.execute(
        select(Resource).where(
            and_(Resource.available == True, Resource.current_load < Resource.capacity)
        )
    )
    resources = resources_result.scalars().all()

    return {
        "zone_id": zone_id,
        "zone_name": zone.name if zone else None,
        "incident": {
            "id": incident.id if incident else None,
            "priority_score": incident.priority_score if incident else 0,
            "disaster_type": incident.disaster_type if incident else None,
            "victim_count": incident.victim_count if incident else 0,
            "status": incident.status if incident else "active",
        } if incident else None,
        "available_resources": len(resources),
        "recent_reports": 0,  # simplified
    }

# ─── NEW: critical_incidents ──────────────────────────────────────────
@router.get("/critical")
async def critical_incidents_endpoint(
    threshold: float = 70.0,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["commander", "responder"])),
):
    """Lists incidents above priority threshold."""
    from sqlalchemy import select

    result = await db.execute(
        select(Incident).where(Incident.priority_score >= threshold, Incident.active == True).limit(3)
    )
    incidents = result.scalars().all()
    return {
        "incidents": [
            {
                "incident_id": inc.id,
                "priority_score": inc.priority_score,
                "disaster_type": inc.disaster_type,
                "victim_count": inc.victim_count or 0,
                "zone_id": inc.zone_id,
            }
            for inc in incidents
        ]
    }

# ─── NEW: incident_reports ────────────────────────────────────────────
@router.get("/reports")
async def incident_reports_endpoint(
    incident_id: str = Query(...),
    limit: int = Query(10),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["commander", "responder"])),
):
    """Lists recent reports for an incident."""
    from sqlalchemy import select

    result = await db.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        return {"reports": [], "total": 0}

    # Query reports related to this incident/zone
    from app.models.report import Report
    report_result = await db.execute(
        select(Report).where(Report.zone_id == incident.zone_id).limit(limit)
    )
    reports = report_result.scalars().all()

    return {
        "reports": [
            {
                "id": r.id,
                "source": r.source,
                "trust_score": r.trust_score,
                "disaster_type": r.disaster_type,
                "excerpt": (r.message_text or r.transcript or "")[:80] if (r.message_text or r.transcript) else "",
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "total": len(reports),
    }

async def _emit_command_interaction(
    user_id: str,
    query: str,
    response: str,
    execution_time: float,
    db: AsyncSession,
) -> None:
    """Emit command center interaction WebSocket event."""
    # Get user ID from context if available
    # In full implementation, would extract from auth context
    await emit_command_interaction(
        user_id="commander",
        query=query,
        response={"response": response, "execution_time": execution_time},
        source="command_center",
    )