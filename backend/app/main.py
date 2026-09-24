"""
AegisAI — Phase 1 FastAPI application.

Mounts Socket.IO alongside the REST API via ASGI middleware.
Starts background pollers (weather, seismic, social) on startup.
"""
import socketio
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.services.websocket import sio
from app.pollers.scheduler import start_scheduler, stop_scheduler
from app.api import reports, incidents, zones, actions, auth, resources, predictions, command, phase2, heatmaps, routes
from app.core.database import AsyncSessionLocal
import importlib
from sqlalchemy import text

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("AegisAI backend starting up")
    try:
        settings.ensure_database_configured()
    except RuntimeError as exc:
        logger.error("Database not configured", error=str(exc))
        raise
    await start_scheduler()
    # Auto-seed demo users/fixtures when DB is empty (API keys optional).
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(text("SELECT 1 FROM users LIMIT 1"))
            row = res.first()
            if not row:
                logger.info("Users table empty — running demo seeder")
                try:
                    seed = importlib.import_module("seed")
                    await seed.seed_users(db)
                    if settings.mapbox_access_token:
                        await seed.seed_fixtures(db)
                    await db.commit()
                    logger.info("Demo seed complete")
                except Exception as e:
                    logger.exception("Seeder failed", error=str(e))
    except Exception as exc:
        logger.error(
            "Auto-seed skipped — cannot reach database",
            error=str(exc),
            database_host=settings.database_url.split("@")[-1].split("/")[0],
        )
    yield
    await stop_scheduler()
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
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "path": str(request.url.path)},
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
    allow_origins=settings.cors_origins,
    allow_credentials=True,
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
app.include_router(auth.router,        prefix="/api/auth",        tags=["auth"])
app.include_router(reports.router,     prefix="/api/reports",     tags=["reports"])
app.include_router(incidents.router,   prefix="/api/incidents",   tags=["incidents"])
app.include_router(zones.router,       prefix="/api/zones",       tags=["zones"])
app.include_router(actions.router,     prefix="/api/actions",     tags=["actions"])
app.include_router(resources.router,   prefix="/api/resources",   tags=["resources"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(routes.router,      prefix="/api/routes",      tags=["routes"])
app.include_router(command.router,     tags=["command center"])  # prefix already set on router
app.include_router(phase2.router,      tags=["phase 2 intelligence"])
app.include_router(heatmaps.router,    tags=["heatmaps"])


@app.get("/api/health", tags=["health"])
async def health():
    import os
    return {
        "status": "ok",
        "version": "1.0.0",
        "build": os.environ.get("AEGIS_BUILD_ID", "unversioned"),
    }


_enable_head_on_get_routes(app.routes)


# ── Socket.IO ASGI mount ──────────────────────────────────────
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Entry point: uvicorn app.main:socket_app
# (socket_app wraps app so WebSocket handshake is handled first)
