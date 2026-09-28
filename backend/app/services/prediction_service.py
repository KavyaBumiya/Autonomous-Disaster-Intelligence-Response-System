"""
Prediction Service v2 — Enhanced flood/fire spread and route intelligence.

Phase 3 deliverable with actual computation primitives that the engine layer
can integrate with DB data. Provides:

- flood: calculate_flood_spread, flood_probability_grid
- fire: calculate_fire_spread, fire_spread_step
- route: compute_alt_route with OSRM fallback awareness
"""
import structlog


logger = structlog.get_logger()


# ── Constants ──────────────────────────────────────────────────────────
EARTH_RADIUS_KM = 6371.0
METERS_PER_DEGREE_LAT = 111_000.0
DEFAULT_GRID_CELLS = 5
MAX_PREDICTION_HOURS = 24