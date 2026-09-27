from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError


class NASAFIRMSConnector(BaseConnector):
    provider = "nasa-firms"
    base_url = "https://firms.modaps.eosdis.nasa.gov/api"
    timeout_seconds = 15.0

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.nasa_firms_api_key

    async def get_active_fires(
        self,
        source: str = "VIIRS_SNPP_NRT",
        area: str = "-180,-90,180,90",
        day_range: int = 1,
    ) -> list[dict[str, Any]]:
        path = f"/area/csv/{self._api_key}/{source}/{area}/{day_range}"
        resp = await self.get(path)
        text = resp.text
        lines = text.strip().split("\n")
        if not lines:
            return []
        headers = lines[0].split(",")
        fires = []
        for line in lines[1:]:
            values = line.split(",")
            if len(values) != len(headers):
                continue
            row = dict(zip(headers, values))
            try:
                fires.append({
                    "latitude": float(row.get("latitude", 0)),
                    "longitude": float(row.get("longitude", 0)),
                    "brightness": float(row.get("brightness", 0)),
                    "scan": float(row.get("scan", 0)),
                    "track": float(row.get("track", 0)),
                    "acq_date": row.get("acq_date"),
                    "acq_time": row.get("acq_time"),
                    "satellite": row.get("satellite"),
                    "confidence": row.get("confidence"),
                    "frp": float(row.get("frp", 0)),
                    "daynight": row.get("daynight"),
                })
            except (ValueError, TypeError):
                continue
        return fires

    async def get_fire_events(
        self,
        lat: float,
        lng: float,
        radius_km: float = 500,
        days: int = 7,
    ) -> dict[str, Any]:
        d_lat = radius_km / 111.32
        cos_lat = max(0.01, __import__("math").cos(__import__("math").radians(lat)))
        d_lng = radius_km / (111.32 * cos_lat)
        area = f"{lng - d_lng},{lat - d_lat},{lng + d_lng},{lat + d_lat}"
        fires = await self.get_active_fires(area=area, day_range=days)
        import math
        filtered = [
            f for f in fires
            if self._haversine(lat, lng, f["latitude"], f["longitude"]) <= radius_km
        ]
        return {
            "source": "NASA FIRMS",
            "satellite": "VIIRS SNPP",
            "count": len(filtered),
            "radius_km": radius_km,
            "days": days,
            "fires": filtered,
        }

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        import math
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lng2 - lng1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))
