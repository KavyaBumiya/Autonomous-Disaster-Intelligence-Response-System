"""
Overpass connector — disaster-relevant OSM infrastructure (PRD §8).

Retrieves roads, bridges, hospitals, clinics, shelters, schools, waterways
and buildings inside a bounding box and normalizes them to
InfrastructureObservation (§5). Nominatim is geocoding only — not a
substitute (§2 note).

Public-API etiquette (§26):
    * module-level 1 req/s throttle (Overpass rate limit)
    * timeout 25 s, max 2 attempts (no aggressive retry against public infra)
    * response size capped (MAX_FEATURES)
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError
from app.schemas.observations import InfrastructureObservation

logger = structlog.get_logger()

MAX_FEATURES = 5000
_THROTTLE_MIN_INTERVAL_S = 1.0
_throttle_lock = asyncio.Lock()
_last_call_at = 0.0

# amenity/category → normalized category (§8 scope)
_AMENITY_CATEGORY = {
    "hospital": "hospital",
    "clinic": "clinic",
    "doctors": "clinic",
    "shelter": "shelter",
    "school": "school",
    "kindergarten": "school",
}
_WATERWAY_CATEGORY = {"river", "stream", "canal", "ditch"}


async def _throttle() -> None:
    """Enforce ≥1 s between Overpass calls (process-wide)."""
    global _last_call_at
    async with _throttle_lock:
        now = time.monotonic()
        wait = _THROTTLE_MIN_INTERVAL_S - (now - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = time.monotonic()


def build_infrastructure_query(south: float, west: float, north: float, east: float) -> str:
    """Overpass QL for disaster-relevant features in a bbox (§8 pattern,
    adapted: nwr for amenities, bridge checked before generic highway)."""
    bbox = f"({south},{west},{north},{east})"
    waterway_alt = "|".join(sorted(_WATERWAY_CATEGORY))
    return (
        "[out:json][timeout:25];\n"
        "(\n"
        f'  way["highway"]{bbox};\n'
        f'  way["bridge"]{bbox};\n'
        f'  nwr["amenity"~"^(hospital|clinic|doctors|shelter|school|kindergarten)$"]{bbox};\n'
        f'  way["waterway"~"^({waterway_alt})$"]{bbox};\n'
        f'  way["building"]{bbox};\n'
        ");\n"
        "out geom;"
    )


def _categorize(tags: dict[str, str]) -> str | None:
    if tags.get("bridge") not in (None, "", "no", "false"):
        return "bridge"
    if tags.get("highway"):
        return "road"
    amenity = tags.get("amenity")
    if amenity in _AMENITY_CATEGORY:
        return _AMENITY_CATEGORY[amenity]
    waterway = tags.get("waterway")
    if waterway in _WATERWAY_CATEGORY:
        return "waterway"
    if tags.get("building") not in (None, "", "no"):
        return "building"
    return None


def _element_coords(el: dict[str, Any]) -> tuple[float, float] | None:
    """node → own coords; way → geometry centroid; relation → center if any."""
    if el.get("type") == "node" and "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    geom = el.get("geometry")
    if geom:
        lats = [g["lat"] for g in geom if isinstance(g, dict) and "lat" in g]
        lons = [g["lon"] for g in geom if isinstance(g, dict) and "lon" in g]
        if lats and lons:
            return sum(lats) / len(lats), sum(lons) / len(lons)
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def normalize_elements(elements: list[dict[str, Any]]) -> list[InfrastructureObservation]:
    """Raw Overpass elements → §5 observations (order preserved, capped)."""
    now = datetime.now(timezone.utc)
    out: list[InfrastructureObservation] = []
    for el in elements:
        if len(out) >= MAX_FEATURES:
            logger.warning("overpass_feature_cap_reached", cap=MAX_FEATURES)
            break
        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        category = _categorize(tags)
        if category is None:
            continue
        coords = _element_coords(el)
        if coords is None:
            continue
        lat, lng = coords
        out.append(
            InfrastructureObservation(
                osm_type=str(el.get("type", "")),
                osm_id=int(el.get("id", 0)),
                category=category,
                lat=lat,
                lng=lng,
                name=tags.get("name"),
                tags={str(k): str(v) for k, v in tags.items()},
                retrieved_at=now,
            )
        )
    return out


class OverpassConnector(BaseConnector):
    provider = "osm/overpass"
    timeout_seconds = 30.0
    # Overpass's dispatcher answers an identical still-registered query with
    # HTTP 200 + an HTML "duplicate_query" error — retryable, but only after
    # a few seconds, hence the wider backoff than the base connector default.
    max_attempts = 3
    backoff_base_seconds = 4.0
    backoff_max_seconds = 20.0

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or get_settings().overpass_api_url

    @property
    def _headers(self) -> dict[str, str]:
        # overpass-api.de answers 406 (Not Acceptable) without an explicit
        # JSON Accept header + identifying User-Agent (verified live).
        return {
            "Accept": "application/json",
            "User-Agent": get_settings().nominatim_user_agent,
        }

    async def fetch_infrastructure(
        self, south: float, west: float, north: float, east: float
    ) -> list[InfrastructureObservation]:
        query = build_infrastructure_query(south, west, north, east)
        await _throttle()
        data = await self.get_json("", params={"data": query}, headers=self._headers)

        if not isinstance(data, dict):
            raise ConnectorError(self.provider, "non-object response", retryable=False)
        if "elements" not in data:
            # Overpass returns {"remark": ...} on runtime errors without elements.
            raise ConnectorError(
                self.provider,
                f"no elements in response (remark={data.get('remark', 'n/a')})",
                retryable=True,
            )
        elements = data["elements"]
        if not isinstance(elements, list):
            raise ConnectorError(self.provider, "'elements' not a list", retryable=False)

        obs = normalize_elements(elements)
        logger.info(
            "overpass_fetch_ok",
            bbox=[south, west, north, east],
            raw_elements=len(elements),
            normalized=len(obs),
        )
        return obs
