"""
AegisAI — Phase 1 FastAPI application.

Mounts Socket.IO alongside the REST API via ASGI middleware.
Starts background pollers (weather, seismic, social) on startup.
"""
import socketio
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.services.websocket import sio
from app.pollers.scheduler import start_scheduler, stop_scheduler
from app.api import reports, incidents, zones, actions, auth, resources, predictions, command, phase2, heatmaps
from app.core.database import AsyncSessionLocal
import importlib
from sqlalchemy import text

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("AegisAI backend starting up")
    await start_scheduler()
    # Auto-seed demo data when all API keys are provided and DB is empty
    try:
        required = [
            settings.twitter_bearer_token,
            settings.mapbox_access_token,
        ]
        if all(required):
            async with AsyncSessionLocal() as db:
                # check whether users table already has data
                res = await db.execute(text("SELECT 1 FROM users LIMIT 1"))
                row = res.first()
                if not row:
                    logger.info("API keys present and DB empty — running demo seeder")
                    try:
                        seed = importlib.import_module("seed")
                        # seed.seed_users and seed.seed_fixtures accept an AsyncSession
                        await seed.seed_users(db)
                        await seed.seed_fixtures(db)
                        await db.commit()
                        logger.info("Demo seed complete")
                    except Exception as e:
                        logger.exception("Seeder failed", error=str(e))
    except Exception:
        logger.exception("Error checking auto-seed conditions")
    yield
    await stop_scheduler()
    logger.info("AegisAI backend shut down")


# ── FastAPI app ───────────────────────────────────────────────
app = FastAPI(
    title="AegisAI API",
    description="AI-powered disaster intelligence & response platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root path & favicon � prevent 404 on / and /favicon.ico
@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API health check for frontend compatibility."""
    return {"message": "AegisAI API", "docs": "/api/health"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return no-content for favicon to prevent 404 console spam."""
    return Response(status_code=204)


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
app.include_router(command.router,     tags=["command center"])  # prefix already set on router
app.include_router(phase2.router,      tags=["phase 2 intelligence"])
app.include_router(heatmaps.router,    tags=["heatmaps"])


@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Socket.IO ASGI mount ──────────────────────────────────────
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Entry point: uvicorn app.main:socket_app
# (socket_app wraps app so WebSocket handshake is handled first)
