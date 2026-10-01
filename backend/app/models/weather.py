import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class WeatherReading(Base):
    __tablename__ = "weather_readings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("zones.id"), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    rainfall_mm_hr: Mapped[float] = mapped_column(Float, default=0.0)
    wind_speed_kmh: Mapped[float] = mapped_column(Float, default=0.0)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure_hpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_main: Mapped[str | None] = mapped_column(String(50), nullable=True)
    weather_description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)  # computed 0.0–1.0
    polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
