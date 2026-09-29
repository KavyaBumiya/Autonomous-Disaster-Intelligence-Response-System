"""
AegisAI — Phase 1 FastAPI application.

Mounts Socket.IO alongside the REST API via ASGI middleware.
Starts background pollers (weather, seismic, social) on startup.
"""
import asyncio
import socketio
import structlog
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.services.websocket import sio
from app.pollers.scheduler import start_scheduler, stop_scheduler
from app.api import reports, incidents, zones, actions, resources, predictions, command, phase2, heatmaps, routes, earthquakes, weather, nasa, maps, openai, firms, traffic, globe, ai, decision, flood

logger = structlog.get_logger()
settings = get_settings()


def _alembic_config():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    return cfg


def _run_alembic_upgrade() -> None:
    """Apply migrations synchronously (used via asyncio.to_thread)."""
    from alembic import command
    command.upgrade(_alembic_config(), "head")


def _stamp_alembic_head() -> None:
    """Mark DB as at head so next boot does not re-run 0001 on existing tables."""
    from alembic import command
    command.stamp(_alembic_config(), "head")


async def _reconcile_missing_columns() -> list[str]:
    """Add model columns missing from pre-existing tables.

    create_all() only creates missing tables — it never ALTERs existing ones,
    and migrations are stamped (not applied), so columns added to the models
    after a table's first creation would 500 at query time (e.g. prod
    reports.geocoding_confidence from migration 0006). Idempotent and cheap:
    inspect every metadata table, ADD COLUMN IF NOT EXISTS for the difference.
    """
    from sqlalchemy import inspect as sa_inspect

    def _sync(sync_conn):
        inspector = sa_inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())
        added: list[str] = []
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all handles missing tables
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                col_type = col.type.compile(dialect=sync_conn.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
                if col.server_default is not None:
                    arg = col.server_default.arg
                    rendered = (
                        str(arg.compile(dialect=sync_conn.dialect))
                        if hasattr(arg, "compile")
                        else str(arg)
                    )
                    ddl += f" DEFAULT {rendered}"
                sync_conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
        return added

    async with engine.begin() as conn:
        return await conn.run_sync(_sync)


# Real monitoring targets for `DEMO_SCENARIO`. A Zone is a place the operator
# watches, not an observation: the coordinates are a real location and every
# reading stored against it is fetched live. Only the geometry is seeded.
DEMO_SCENARIO_ZONES: dict[str, dict] = {
    "vadodara_flood": {
        "name": "Vadodara Basin",
        "centroid_lat": 22.3072,
        "centroid_lng": 73.1812,
        "radius_meters": 800.0,
    },
}


async def _ensure_demo_zone() -> None:
    """Create the scenario's monitoring zone when the zones table is empty.

    Every panel that needs a zone iterates `zones` — the weather poller returns
    immediately on an empty list, and the console picks its primary zone from
    the same list. On a cold database the demo therefore opens onto blank
    panels until somebody POSTs a zone by hand.
    """
    scenario = (get_settings().demo_scenario or "").strip()
    if not scenario:
        return
    spec = DEMO_SCENARIO_ZONES.get(scenario)
    if spec is None:
        logger.warning("unknown_demo_scenario", scenario=scenario,
                       known=sorted(DEMO_SCENARIO_ZONES))
        return

    from app.core.database import AsyncSessionLocal
    from app.models.zone import Zone

    try:
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(select(func.count(Zone.id)))).scalar_one()
            if existing:
                return
            db.add(Zone(**spec, geometry=None))
            await db.commit()
            logger.info("demo zone bootstrapped", scenario=scenario, **spec)
    except Exception as exc:  # noqa: BLE001 - never block boot on this
        logger.warning("demo zone bootstrap failed", scenario=scenario,
                       error=type(exc).__name__, detail=str(exc)[:200])


async def _ensure_schema() -> None:
    """Create extensions + full schema from models.

    No demo rows are inserted: every record in the database originates from a
    live provider (USGS, NASA EONET/FIRMS, weather, traffic) or from an
    operator-declared entity such as a zone created through POST /api/zones.
    """
    import app.models  # noqa: F401 — register models for create_all
    from app.models.user import User

    # Extensions required by Geometry columns / migrations
    async with engine.begin() as conn:
        for ext in ("postgis", "pgcrypto"):
            try:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
            except Exception as exc:
                logger.warning("Could not enable extension", ext=ext, error=str(exc))

    # Full schema from ORM models (source of truth for the running app)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("metadata.create_all complete")
        # create_all never ALTERs — repair model/table drift before stamping
        try:
            added = await _reconcile_missing_columns()
            if added:
                logger.warning("schema_columns_added", columns=added)
            else:
                logger.info("schema reconcile — no missing columns")
        except Exception as exc:
            logger.warning("column reconcile failed", error=str(exc))
        # Tables now match models — stamp head so alembic does not re-create them
        await asyncio.to_thread(_stamp_alembic_head)
        logger.info("Alembic stamped at head")
    except Exception as exc:
        logger.error("create_all/stamp failed", error=str(exc), error_type=type(exc).__name__)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: User.__table__.create(c, checkfirst=True))
        # Fresh DB without full schema: try real migrations
        try:
            await asyncio.to_thread(_run_alembic_upgrade)
            logger.info("Alembic migrations applied")
        except Exception as exc2:
            logger.warning("Alembic failed after partial create_all", error=str(exc2))

    # Ensure the users table exists. Rows are no longer seeded — auth is public
    # and nothing in the request path reads this table.
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: User.__table__.create(c, checkfirst=True))

    await _ensure_demo_zone()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("AegisAI backend starting up")
    try:
        settings.ensure_database_configured()
    except RuntimeError as exc:
        logger.error("Database not configured", error=str(exc))
        raise
    try:
        await _ensure_schema()
    except Exception as exc:
        logger.error("Schema/seed bootstrap failed", error=str(exc))
    try:
        await start_scheduler()
    except Exception as exc:
        # start_scheduler already isolates per-poller import failures, so
        # reaching here means the scheduler itself is broken. Log it and keep
        # serving: the API is still useful, and every panel reads DEGRADED
        # rather than the process refusing to bind its port.
        logger.error("Scheduler failed to start", error=type(exc).__name__,
                     detail=str(exc)[:200])
    yield
    await stop_scheduler()
    from app.integrations.cache import _client as redis_client
    if redis_client is not None:
        try:
            await redis_client.aclose()
        except Exception:
            pass
    logger.info("AegisAI backend shut down")


# ── FastAPI app ───────────────────────────────────────────────
class GetWithHeadRoute(APIRoute):
    """APIRoute that also accepts HEAD whenever GET is allowed.

    FastAPI's APIRoute does not auto-add HEAD (unlike Starlette's Route),
    so health checkers probing HEAD / get 405 without this.
    """

    def __init__(self, path: str, endpoint, **kwargs):
        methods = kwargs.get("methods")
        if methods:
            normalized = {str(m).upper() for m in methods}
            if "GET" in normalized:
                normalized.add("HEAD")
                kwargs["methods"] = sorted(normalized)
        super().__init__(path, endpoint, **kwargs)


app = FastAPI(
    title="AegisAI API",
    description="AI-powered disaster intelligence & response platform",
    version="1.0.0",
    lifespan=lifespan,
)
app.router.route_class = GetWithHeadRoute


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    """Never return a bare 500 body — log and return JSON."""
    logger.exception("Unhandled error", path=str(request.url.path), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"{type(exc).__name__}: {exc}",
            "path": str(request.url.path),
        },
    )


def _enable_head_on_get_routes(routes) -> None:
    """Ensure every registered GET APIRoute also allows HEAD.

    include_router preserves each sub-router's route class, so routes pulled
    in from APIRouter modules still need a post-registration pass.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            methods = route.methods
            if methods and "GET" in methods:
                methods.add("HEAD")
        children = getattr(route, "routes", None)
        if children:
            _enable_head_on_get_routes(children)
        original = getattr(route, "original_router", None)
        if original is not None and hasattr(original, "routes"):
            _enable_head_on_get_routes(original.routes)


app.add_middleware(
    CORSMiddleware,
    # FRONTEND_ORIGIN env (comma-separated). Empty = ["*"] for local demo.
    # Set it to the console's deployed origin(s) to lock cross-origin access
    # down to your own frontend.
    allow_origins=settings.cors_origins,
    # Development-only pattern that also admits a Vite server that moved off
    # 5173, so REST and the Socket.IO handshake accept the same origins.
    allow_origin_regex=settings.cors_origin_regex,
    # Only with explicit origins: a wildcard origin cannot legally be combined
    # with credentials. The demo authenticates with bearer tokens, so a wildcard
    # origin still works for it.
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root path & favicon — prevent 404 on / and /favicon.ico
@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API health check for frontend compatibility."""
    return {"message": "AegisAI API", "docs": "/api/health"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return no-content for favicon to prevent 404 console spam."""
    return Response(status_code=204)


# ── API root metadata (GET /api) ─────────────────────────────
@app.get("/api", tags=["root"])
async def api_root():
    """API discovery endpoint — JSON metadata, not Swagger UI."""
    return {
        "name": "AegisAI API",
        "description": "AI-powered disaster intelligence & response platform",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs",
        "health": "/api/health",
    }


# ── Static files (audio uploads) ─────────────────────────────
app.mount("/media", StaticFiles(directory=settings.media_dir, check_dir=False), name="media")

# ── REST routers ─────────────────────────────────────────────
app.include_router(reports.router,     prefix="/api/reports",     tags=["reports"])
app.include_router(incidents.router,   prefix="/api/incidents",   tags=["incidents"])
app.include_router(zones.router,       prefix="/api/zones",       tags=["zones"])
app.include_router(actions.router,     prefix="/api/actions",     tags=["actions"])
app.include_router(resources.router,   prefix="/api/resources",   tags=["resources"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(routes.router,      prefix="/api/routes",      tags=["routes"])
app.include_router(earthquakes.router, prefix="/api/earthquakes", tags=["earthquakes"])
app.include_router(command.router,     tags=["command center"])  # prefix already set on router
app.include_router(phase2.router,      tags=["phase 2 intelligence"])
app.include_router(heatmaps.router,    tags=["heatmaps"])
app.include_router(weather.router,     prefix="/api/weather", tags=["weather"])
app.include_router(nasa.router,        prefix="/api/nasa",    tags=["nasa"])
app.include_router(maps.router,       prefix="/api/maps",   tags=["maps"])
app.include_router(openai.router,     prefix="/api/openai", tags=["openai"])
app.include_router(firms.router,      prefix="/api/firms",  tags=["nasa-firms"])
app.include_router(traffic.router,    prefix="/api/traffic", tags=["tomtom"])
app.include_router(globe.router,      prefix="/api/globe",  tags=["cesium-ion"])
app.include_router(ai.router,         tags=["ai"])
app.include_router(decision.router,   tags=["decision"])
app.include_router(flood.router,      prefix="/api/flood", tags=["flood"])


async def _database_ping() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT 1"))


async def _cache_ping() -> None:
    from app.integrations import cache

    client = await cache.get_redis()
    await client.ping()


async def _probe_database() -> str:
    """DB liveness for /api/health (failure matrix, §31)."""
    try:
        await asyncio.wait_for(_database_ping(), timeout=3.0)
        return "ONLINE"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_db_probe_failed", error=str(exc))
        return "OFFLINE"


async def _probe_cache() -> str:
    """Redis liveness for /api/health (failure matrix, §31)."""
    try:
        await asyncio.wait_for(_cache_ping(), timeout=2.0)
        return "ONLINE"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_cache_probe_failed", error=str(exc))
        return "DEGRADED"


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Cheap process liveness.

    Touches no database, cache or provider, so it answers in milliseconds and
    cannot fail for an unrelated reason. This is what a container platform
    should poll: a transient database blip must not make the platform consider
    the process dead and restart it.

    `/readyz` covers "can serve traffic" and `/api/health` the detailed
    operational picture. The three are deliberately distinct.
    """
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz():
    """Readiness: the process is up AND the database is reachable.

    Returns 503 when the database is not, so a load balancer or orchestrator can
    hold traffic back until the app can actually serve it. The cache is
    optimisation only and never blocks readiness.
    """
    db_status = await _probe_database()
    ready = db_status == "ONLINE"
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "database": db_status},
    )


@app.get("/api/health", tags=["health"])
async def health():
    import os
    from app.integrations import registry

    raw = registry.snapshot()
    # Raw provider names kept (frontend reads open-meteo/usgs) plus canonical
    # group aliases {weather, seismic, gis, routing, geocoding, ai} (§31).
    providers: dict = dict(raw)
    for group, status in registry.canonical_statuses(raw).items():
        providers[group] = {"status": status, "canonical": True}

    db_status = await _probe_database()
    cache_status = await _probe_cache()

    reasons: list[str] = []
    if db_status != "ONLINE":
        reasons.append(f"database {db_status}")
    if cache_status != "ONLINE":
        reasons.append(f"cache {cache_status} (optimisation only — never blocks)")

    return {
        "status": "degraded" if reasons else "ok",
        "version": "1.0.0",
        "build": os.environ.get("AEGIS_BUILD_ID", "unversioned"),
        # Additive (§31): external provider status for DEGRADED detection.
        "providers": providers,
        # Additive (Phase 16 failure matrix): core dependency probes.
        "services": {"database": db_status, "cache": cache_status},
        "reasons": reasons,
    }


_enable_head_on_get_routes(app.routes)


# ── Socket.IO ASGI mount ──────────────────────────────────────
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Entry point: uvicorn app.main:socket_app
# (socket_app wraps app so WebSocket handshake is handled first)
