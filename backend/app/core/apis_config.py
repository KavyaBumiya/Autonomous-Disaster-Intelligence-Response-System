"""
AegisAI — Dataset & API Configuration Module.

Centralized configuration for all external data sources and APIs used by the system.
Organized by priority and usage category based on the project's research phase analysis.
"""

from typing import Dict, List, Any, Optional

# ─── Weather APIs ──────────────────────────────────────────────────────
WEATHER_APIS = {
    "open-meteo": {
        "forecast": "https://api.open-meteo.com/v1/forecast",
        "era5": "https://archive-api.open-meteo.com/v1/era5",
        "description": "Current weather and historical climate data",
        "parameters": {
            "latitude": "float",
            "longitude": "float",
            "hourly": "comma-separated list of hourly variables",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
        },
        "use_cases": [
            "flood prediction rainfall input",
            "fire weather risk assessment",
            "real-time weather monitoring",
        ],
    },
    "noaa-ncei": {
        "base": "https://www.ncei.noaa.gov/cdo-web/api/v2",
        "description": "NOAA Climate Data Online API",
        "use_cases": ["historical climate analysis", "trend analysis"],
    },
}

# ─── Earth Observation APIs ──────────────────────────────────────────
EARTH_OBS_APIS = {
    "copernicus-sentinel": {
        "stac_catalog": "https://catalogue.dataspace.copernicus.eu/stac",
        "processing_api": "https://sh.dataspace.copernicus.eu/api/v1/process",
        "description": "Sentinel-1/2 satellite imagery and data",
        "use_cases": [
            "flood extent mapping",
            "fire burn scar detection",
            "vegetation change detection",
        ],
    },
    "cmr-earthdata": {
        "collections": "https://cmr.earthdata.nasa.gov/search/collections.json",
        "granules": "https://cmr.earthdata.nasa.gov/search/granules.json",
        "stac": "https://cmr.earthdata.nasa.gov/search/collections.stac",
        "description": "NASA Earthdata CMR collections and granules",
        "use_cases": [
            "dataset discovery",
            "precipitation data (GPM/IMERG)",
            "geospatial metadata",
        ],
        "priority": "required",
    },
    "usgs-earthquakes": {
        "event": "https://earthquake.usgs.gov/fdsnws/event/1/query",
        "realtime": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php",
        "description": "USGS earthquake data",
        "use_cases": ["seismic event detection", "early warning"],
    },
}

# ─── Geospatial & Road APIs ──────────────────────────────────────────
GEOSPATIAL_APIS = {
    "openstreetmap": {
        "nominatim_geocode": "https://nominatim.openstreetmap.org/",
        "overpass_api": "https://overpass-api.de/api/interpreter",
        "description": "OpenStreetMap geospatial data",
        "use_cases": [
            "road network analysis",
            "building footprints",
            "point of interest search",
        ],
        "rate_limit": "1 request/second",
    },
    "osrm_routing": {
        "base": "https://router.project-osrm.org/",
        "description": "Open Source Routing Machine",
        "use_cases": ["route planning", "detour calculation"],
    },
}

# ─── Disaster & Humanitarian APIs ────────────────────────────────────
DISASTER_APIS = {
    "usgs": {
        "earthquake": "https://earthquake.usgs.gov/fdsnws/event/1/query",
        "realtime": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php",
        "description": "USGS earthquake and disaster data",
        "use_cases": ["seismic event detection", "aftershock prediction"],
    },
    "reliefweb": {
        "api": "https://api.reliefweb.int/v1/",
        "description": "Humanitarian disaster reports",
        "use_cases": ["humanitarian situation reports", "SOS alerts"],
    },
    "em-dat": {
        "description": "EM-DAT international disaster database",
        "use_cases": ["historical disaster records", "disaster trend analysis"],
        "note": "Dataset - not a live API",
    },
}

# ─── AegisAI Internal APIs ───────────────────────────────────────────
INTERNAL_APIS = {
    "fastapi": {
        "base": "/api",
        "endpoints": {
            "reports": "/api/reports",
            "incidents": "/api/incidents",
            "zones": "/api/zones",
            "resources": "/api/resources",
            "predictions": "/api/predictions",
            "command": "/api/command",
            "auth": "/api/auth",
        },
        "description": "AegisAI internal REST API",
    },
    "socketio": {
        "events": [
            "new_report",
            "trust_score_updated",
            "incident_priority_updated",
            "new_incident",
            "action_state_changed",
            "prediction_updated",
            "route_changed",
            "resource_assigned",
            "command_center_interaction",
        ],
        "rooms": ["global_feed", "zone_{zone_id}"],
    },
}

# ─── Configuration ───────────────────────────────────────────────────
API_CONFIG = {
    "default_weather_api": "open-meteo",
    "default_earth_obs": "cmr-earthdata",
    "cache_ttl_seconds": 300,  # 5 minutes
    "rate_limits": {
        "open-meteo": "unlimited",  # public API without auth
        "overpass": "1 req/sec",
        "nominatim": "1 req/sec",
        "cmr": "auth required",
    },
}


# ─── Helper Functions ──────────────────────────────────────────────────

def get_weather_api_config(api_name: str = "open-meteo") -> Dict[str, Any]:
    """Get weather API configuration by name."""
    return WEATHER_APIS.get(api_name, WEATHER_APIS["open-meteo"])


def get_cmr_config() -> Dict[str, Any]:
    """Get NASA CMR API configuration."""
    return EARTH_OBS_APIS["cmr-earthdata"]


def get_geospatial_config(api_name: str = "openstreetmap") -> Dict[str, Any]:
    """Get geospatial API configuration by name."""
    return GEOSPATIAL_APIS.get(api_name, GEOSPATIAL_APIS["openstreetmap"])


def is_api_available(api_name: str) -> bool:
    """Check if an API is configured and available."""
    config = API_CONFIG.get("rate_limits", {})
    return api_name in config


# ─── Export ──────────────────────────────────────────────────────────
__all__ = [
    "WEATHER_APIS",
    "EARTH_OBS_APIS",
    "GEOSPATIAL_APIS",
    "DISASTER_APIS",
    "INTERNAL_APIS",
    "API_CONFIG",
    "get_weather_api_config",
    "get_cmr_config",
    "get_geospatial_config",
    "is_api_available",
]