"""AegisAI external-data connector layer (PRD §4).

Package layout (populated incrementally across phases):
    integrations/
        base.py       — BaseConnector (async HTTP, timeout, retry, errors)
        registry.py   — provider status registry (feeds /api/health §31)
        cache.py      — Redis cache helpers for provider responses (§27)
        weather/      — open_meteo.py        (Phase 2)
        gis/          — overpass.py, nominatim.py, osrm.py  (Phases 3–5)
        seismic/      — usgs.py              (Phase 6)
        satellite/    — base.py, provider.py (Phase 3-satellite: abstraction only)
"""
