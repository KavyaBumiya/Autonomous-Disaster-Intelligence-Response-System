import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, Text, ForeignKey, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_id: Mapped[str] = mapped_column(String(36), ForeignKey("zones.id"), nullable=False)
    disaster_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    xai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")  # active|resolved|false_alarm
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    victim_count: Mapped[int] = mapped_column(Integer, default=0)
    victim_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    zone: Mapped["Zone"] = relationship("Zone", back_populates="incidents")
    agent_outputs: Mapped[list["AgentOutput"]] = relationship("AgentOutput", back_populates="incident", lazy="select")
    actions: Mapped[list["Action"]] = relationship("Action", back_populates="incident", lazy="select")
