"""
AEGIS-AI — Central configuration
==================================
All settings are loaded from environment variables (server-side .env).
The NVIDIA_API_KEY is loaded here and never serialised into any HTTP response.
"""
from functools import lru_cache
from pathlib import Path
import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Search order: CWD .env → project root .env → backend/.env
# (local uvicorn often runs with CWD=backend/, Docker injects env vars directly)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../backend
_PROJECT_ROOT = _BACKEND_ROOT.parent                 # repo root
_ENV_FILES = (
    Path(".env"),
    _PROJECT_ROOT / ".env",
    _BACKEND_ROOT / ".env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _ENV_FILES),
        extra="ignore",
        env_prefix="",
    )

    # ── Database ──────────────────────────────────────────────────────────
    # Overridden by DATABASE_URL. Default is Docker-Compose only (host `db`).
    database_url: str = "postgresql+asyncpg://aegisai:aegisai_secret@db:5432/aegisai"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        """Normalise Render/Heroku postgres:// URLs to asyncpg dialect."""
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        # Render/managed Postgres requires SSL; asyncpg reads ?ssl=require
        if "ssl=" not in v and "sslmode=" not in v:
            host_part = v.split("@", 1)[-1].split("/", 1)[0]
            host = host_part.split(":", 1)[0]
            if host not in {"localhost", "127.0.0.1", "db", "postgres"}:
                v = f"{v}{'&' if '?' in v else '?'}ssl=require"
        return v

    def ensure_database_configured(self) -> None:
        """Fail fast on Render when DATABASE_URL still points at Docker host `db`."""
        import os

        host_part = self.database_url.split("@", 1)[-1].split("/", 1)[0]
        host = host_part.split(":", 1)[0]
        on_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))
        if on_render and host in {"db", "postgres"}:
            raise RuntimeError(
                "DATABASE_URL is not set (still using Docker host "
                f"'{host}'). On Render: set DATABASE_URL to the "
                "aegisai-db *External Database URL*."
            )

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Auth ──────────────────────────────────────────────────────────────
    jwt_secret:         str = "local-dev-secret-change-in-production"
    jwt_algorithm:      str = "HS256"
    jwt_expire_minutes: int = 60

    # ── NVIDIA NIM AI Gateway ────────────────────────────────────────────
    # OpenAI-compatible endpoint (https://integrate.api.nvidia.com/v1).
    # SECURITY: this key is read server-side only. It is NEVER sent to the
    # browser or included in any HTTP response body.
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Verified reachable on the NIM catalog with a valid key. The previously
    # hard-coded default (deepseek-ai/deepseek-v4.1-flash) is still published
    # but does not answer /chat/completions in time — it burned the full 60s
    # timeout across all 3 attempts and surfaced as "AI provider unreachable",
    # so a deployment that omitted NVIDIA_MODEL looked identical to one with a
    # bad key.
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    # Empty = no alternate. Left empty deliberately: a fallback that itself
    # hangs costs another 3x60s before the caller sees a result, and no second
    # model has been verified to answer, so a slow default would be worse than
    # a fast failure.
    nvidia_fallback_model: str = ""
    nvidia_timeout_seconds: float = 60.0
    # Safety cap on the agentic tool-calling loop (rounds of tool execution).
    nvidia_max_tool_rounds: int = 5

    # ── External data APIs (PRD §35 — connector base URLs) ──────────────
    # Defaults match the previously hard-coded values, so adding these
    # settings changes nothing until env overrides are provided.
    usgs_api_base:           str = "https://earthquake.usgs.gov/fdsnws/event/1"
    usgs_feed_url:           str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    open_meteo_api_base:     str = "https://api.open-meteo.com/v1"
    open_meteo_archive_base: str = "https://archive-api.open-meteo.com/v1/era5"
    overpass_api_url:        str = "https://overpass-api.de/api/interpreter"
    osrm_api_base:           str = "https://router.project-osrm.org"
    nominatim_base_url:      str = "https://nominatim.openstreetmap.org"
    # Fallback providers (used when the primary source is unavailable):
    # MET Norway Locationforecast (keyless; identifying UA required by policy)
    # and Photon/Komoot geocoder (keyless OSM-based, cloud-IP friendly).
    met_norway_base_url:     str = "https://api.met.no/weatherapi/locationforecast/2.0"
    met_norway_user_agent:   str = "AegisAI/1.0 (disaster-response monitoring; contact: ops@aegis.local)"
    photon_base_url:         str = "https://photon.komoot.io"
    reliefweb_api_url:       str = "https://api.reliefweb.int/v1/"
    twitter_bearer_token:    str = ""
    mapbox_access_token:     str = ""
    nominatim_user_agent:    str = "AegisAI/1.0"

    # ── NASA (api.nasa.gov Open APIs + EONET event catalog) ───────────────
    # NASA_API_KEY: developer key for api.nasa.gov services (default limit
    #   1,000 req/h). Server-side only — never in Vercel or responses.
    # EONET (eonet.gsfc.nasa.gov/api/v3) is open and keyless; the key is
    #   forwarded only when set (EONET tolerates the extra param).
    # NOTE: this is NOT Earthdata/CMR authentication (separate ecosystem).
    nasa_api_key:               str = ""
    nasa_api_base:              str = "https://api.nasa.gov"
    eonet_base_url:             str = "https://eonet.gsfc.nasa.gov/api/v3"
    eonet_poll_interval_minutes: int = 10

    # ── Google Maps ─────────────────────────────────────────────────────────
    google_maps_api_key: str = ""

    # ── OpenAI ───────────────────────────────────────────────────────────────
    openai_api_key: str = ""

    # ── NASA FIRMS ───────────────────────────────────────────────────────────
    nasa_firms_api_key: str = ""
    nasa_firms_base_url: str = "https://firms.modaps.eosdis.nasa.gov/api"

    # ── TomTom ───────────────────────────────────────────────────────────────
    tomtom_api_key: str = ""
    tomtom_base_url: str = "https://api.tomtom.com"

    # ── Cesium Ion ───────────────────────────────────────────────────────────
    cesium_ion_token: str = ""
    cesium_ion_asset_id: int = 0

    # ── Evidence fusion (PRD §15 — optional 7th priority factor) ─────────
    # 0.0 (default) keeps the PRD 6-factor formula unchanged; raise
    # (e.g. 0.05) to let fused external evidence nudge the score.
    evidence_factor_weight: float = 0.0

    # ── Social media polling ──────────────────────────────────────────────
    social_enabled:               bool = True
    social_hashtags:              str = "#flood,#earthquake,#cyclone,#fire,#disaster,#SOS,#rescue"
    social_poll_interval_seconds: int = 60
    social_provider:              str = "twitter"   # "twitter" | "mastodon"

    # ── Speech-to-text ───────────────────────────────────────────────────
    # The NVIDIA NIM chat-completions endpoint has no speech-to-text model, so
    # transcription runs locally via openai-whisper. Set STT_PROVIDER=disabled
    # to reject voice reports outright instead of loading the local model.
    stt_provider:                str = "local"
    whisper_model:                  str = "base"
    whisper_max_duration_seconds:   int = 30

    # ── NLP ───────────────────────────────────────────────────────────────
    nlp_model_path:    str = "models/nlp/v1"
    nlp_model_version: str = "v1_distilbert"

    # ── Hugging Face ──────────────────────────────────────────────────────
    # HUGGINGFACE_TOKEN: HF Hub API token for remote inference. Server-side only.
    # When empty, HF provider reports OFFLINE — no fabrication, graceful degradation.
    huggingface_token: str = ""
    huggingface_api_base: str = "https://huggingface.co"
    huggingface_timeout_seconds: float = 30.0
    # Comma-separated model ids to preload at startup (empty = lazy-load on first use)
    huggingface_preload_models: str = ""

    # ── App / media ───────────────────────────────────────────────────────
    media_dir:     str = "media/audio"
    app_env:       str = "development"
    # Comma-separated browser origins for CORS. Empty = allow all (local demo).
    frontend_origin: str = ""

    @property
    def cors_origins(self) -> list[str]:
        raw = (self.frontend_origin or "").strip()
        if not raw:
            return ["*"]
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins or ["*"]

    @property
    def is_development(self) -> bool:
        return (self.app_env or "").strip().lower() in {"dev", "development", "local"}

    @property
    def cors_origin_regex(self) -> str | None:
        """Extra origin pattern for local dev servers.

        Vite claims 5173 but silently falls back to 5174+ when that port is busy,
        and the browser then sends an Origin the API does not recognise, breaking
        the Socket.IO handshake. During development any loopback port is accepted
        so an auto-incremented port cannot break the console. This is scoped to
        development on purpose: production keeps the explicit FRONTEND_ORIGIN
        allowlist and no pattern matching.
        """
        if not self.is_development:
            return None
        return r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

    def is_origin_allowed(self, origin: str | None) -> bool:
        """Single origin check shared by REST CORS and the Socket.IO handshake.

        Used as the `cors_allowed_origins` callable for python-socketio, whose
        engine compares the Origin header verbatim against a list, and mirrored by
        `cors_origin_regex` for Starlette's CORSMiddleware. Keeping both derived
        from here stops the REST API and the socket from disagreeing about which
        browsers are allowed in.
        """
        if not origin:
            # Non-browser clients (curl, health checks, the e2e smoke test) send
            # no Origin. There is no cross-origin risk to police, so allow it.
            return True
        if "*" in self.cors_origins:
            return True
        if origin in self.cors_origins:
            return True
        pattern = self.cors_origin_regex
        if pattern and re.match(pattern, origin):
            return True
        return False

    @property
    def cors_allow_credentials(self) -> bool:
        """Credentialed CORS is only valid against explicit origins.

        The CORS spec forbids combining a wildcard `Access-Control-Allow-Origin`
        with credentials, so cookies are enabled only once FRONTEND_ORIGIN
        names real origins. Requests to this API are currently unauthenticated
        and carry no credentials, so a wildcard origin is workable.
        """
        return "*" not in self.cors_origins

    @property
    def social_hashtag_list(self) -> list[str]:
        return [h.strip() for h in self.social_hashtags.split(",")]

    @property
    def nvidia_configured(self) -> bool:
        return bool(self.nvidia_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
