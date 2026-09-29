import uuid
from datetime import datetime
from sqlalchemy import String, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id"), nullable=False)
    zone_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("zones.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)  # dispatch|alert|evacuate
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_by: Mapped[str] = mapped_column(String(80), default="decision_engine")
    status: Mapped[str] = mapped_column(String(30), default="pending_approval")
    # pending_approval | approved | rejected | dispatched | completed
    # Free-form actor label, not a FK to users.id. This deployment is
    # unauthenticated (see app/auth/dependencies.py) and users are no longer
    # seeded, so the previous ForeignKey pointed at an empty table: every
    # approve/reject wrote the constant "operator" into it and raised an
    # IntegrityError on any database built by Base.metadata.create_all, while an
    # Alembic-built one (migration 0001 creates the column without the FK)
    # silently accepted it. The same code path failed or succeeded depending on
    # how the database was provisioned.
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    incident: Mapped["Incident"] = relationship("Incident", back_populates="actions")
