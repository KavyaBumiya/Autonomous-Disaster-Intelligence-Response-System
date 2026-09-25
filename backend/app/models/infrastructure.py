import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Infrastructure(Base):
    """Disaster-relevant OSM feature ingested via Overpass (PRD §8).

    Stored as a POINT (centroid for ways) with lat/lng kept authoritative;
    `geometry` is populated by ST_MakePoint after insert (asyncpg-safe) and
    indexed GIST for spatial queries (§9)."""

    __tablename__ = "infrastructure"

    __table_args__ = (
        Index("uq_infrastructure_osm", "osm_type", "osm_id", unique=True),
        Index("ix_infrastructure_category", "category"),
        # NOTE: the GIST spatial index is auto-created by GeoAlchemy2
        # as idx_infrastructure_geometry — do not declare a second one.
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    osm_type: Mapped[str] = mapped_column(String(10), nullable=False)   # node|way|relation
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    geometry = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    zone_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("zones.id"), nullable=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
