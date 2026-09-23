import uuid
from sqlalchemy import String, Float, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # team|vehicle|supply|shelter
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    current_load: Mapped[int] = mapped_column(Integer, default=0)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_zone_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
