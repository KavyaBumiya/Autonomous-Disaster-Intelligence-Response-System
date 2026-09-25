import uuid
from datetime import datetime
from sqlalchemy import String, Float, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry
from app.core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("zones.id"), nullable=True)
    reporter_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Content
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)       # Whisper output
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)

    # Classification (NLP output)
    disaster_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nlp_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    geocoding_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    informative_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    nlp_model_version: Mapped[str] = mapped_column(String(20), default="v0_keyword")

    # Source & trust  (Phase 1 additions)
    source: Mapped[str] = mapped_column(String(30), default="citizen_text")
    trust_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    social_post_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Device metadata
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    zone: Mapped["Zone"] = relationship("Zone", back_populates="reports")
    audio_upload: Mapped["AudioUpload | None"] = relationship("AudioUpload", back_populates="report", uselist=False)
