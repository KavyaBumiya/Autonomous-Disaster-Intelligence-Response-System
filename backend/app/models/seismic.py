import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class SeismicEvent(Base):
    __tablename__ = "seismic_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    usgs_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    depth_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    place_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0–1.0 based on magnitude
    polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
