import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry
from app.core.database import Base


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str | None]       = mapped_column(String(255), nullable=True)
    centroid_lat: Mapped[float]    = mapped_column(Float, nullable=False)
    centroid_lng: Mapped[float]    = mapped_column(Float, nullable=False)
    radius_meters: Mapped[float]   = mapped_column(Float, default=500.0)
    geometry                       = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326), nullable=True
    )

    # Priority & victim summary (updated by Decision Engine)
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    victim_count: Mapped[int | None]     = mapped_column(Integer, nullable=True, default=0)

    # Relative population density (0–1), supplied by the operator when the zone
    # is declared. NULL means unknown and is treated as neutral by the
    # Decision Engine rather than guessed from the zone name.
    density_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Soft-delete (added in migration 0003)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                          server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    reports:   Mapped[list["Report"]]   = relationship("Report",   back_populates="zone", lazy="select")
    incidents: Mapped[list["Incident"]] = relationship("Incident", back_populates="zone", lazy="select")
