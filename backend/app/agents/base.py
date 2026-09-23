"""
Frozen AgentInput / AgentOutput contracts.
All agents MUST accept AgentInput and return AgentOutput.
This interface is stable across all phases.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass
class AgentInput:
    incident_id: str
    zone_id: str
    report_ids: list[str]
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentOutput:
    agent_name: str
    incident_id: str
    output_type: Literal["classification", "score", "recommendation", "alert"]
    payload: dict[str, Any]
    confidence: float           # 0.0 – 1.0
    reasoning: str              # human-readable XAI justification
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "incident_id": self.incident_id,
            "output_type": self.output_type,
            "payload": self.payload,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
        }
