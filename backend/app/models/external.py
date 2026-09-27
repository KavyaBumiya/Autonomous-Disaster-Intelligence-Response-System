import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExternalObservation(Base):
    """Generic external observation (PRD §5/§7).

    Only for NON-domain feeds (satellite abstraction, ReliefWeb, manual
    imports…). Weather lives in `weather_readings`, seismic in
    `seismic_events`, GIS in `infrastructure` — no duplication (§28)."""

    __tablename__ = "external_observations"

    __table_args__ = (
        Index("ix_external_observations_source_time", "source", "retrieved_at"),
        Index("ix_external_observations_type", "observation_type"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Evidence(Base):
    """Incident-attached evidence record (PRD §5 / §15).

    payload holds the full normalized observation (JSONB); confidence is
    promoted for indexing/filtering. Written by the evidence fusion
    service — the AI layer never computes final trust (§11)."""

    __tablename__ = "evidence"

    __table_args__ = (
        Index("ix_evidence_incident_id", "incident_id"),
        Index("ix_evidence_source", "source"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    incident_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("incidents.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
