"""
AEGIS-AI — Central configuration
==================================
All settings are loaded from environment variables (server-side .env).
The GROQ_API_KEY is loaded here and never serialised into any HTTP response.
"""
from functools import lru_cache
from pathlib import Path

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

    # ── Groq AI Gateway ───────────────────────────────────────────────────
    # SECURITY: This key is read server-side only. It is NEVER sent to the
    # browser or included in any HTTP response body.
    groq_api_key: str = ""
    # Models confirmed available on this key (checked via client.models.list()):
    #   qwen/qwen3.8-27b             — primary chat / parse / summarise / explain
    #   openai/gpt-oss-20b/120b      — listed but return EMPTY completions (do not use)
    #   whisper-large-v3-turbo       — cloud speech-to-text
    #   allam-2-7b                   — Arabic translate / multilingual normalise
    #   meta-llama/llama-prompt-guard-2-86m — moderation reference model
    # DO NOT use llama-3.x or mixtral — not available on this key's tier.
    groq_model:            str = "qwen/qwen3.8-27b"
    # Empty = no alternate (recommended until another model is verified).
    groq_fallback_model:   str = ""
    groq_stt_model:        str = "whisper-large-v3-turbo"
    groq_translate_model:  str = "allam-2-7b"
    groq_moderation_model: str = "meta-llama/llama-prompt-guard-2-86m"

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
    reliefweb_api_url:       str = "https://api.reliefweb.int/v1/"
    twitter_bearer_token:    str = ""
    mapbox_access_token:     str = ""
    nominatim_user_agent:    str = "AegisAI/1.0"

    # ── Evidence fusion (PRD §15 — optional 7th priority factor) ─────────
    # 0.0 (default) keeps the PRD 6-factor formula unchanged; raise
    # (e.g. 0.05) to let fused external evidence nudge the score.
    evidence_factor_weight: float = 0.0

    # ── Social media polling ──────────────────────────────────────────────
    social_hashtags:              str = "#flood,#earthquake,#cyclone,#fire,#disaster,#SOS,#rescue"
    social_poll_interval_seconds: int = 60
    social_provider:              str = "twitter"   # "twitter" | "mastodon"

    # ── Speech-to-text ───────────────────────────────────────────────────
    # "groq" = cloud Whisper on Groq (preferred); "local" = openai-whisper.
    stt_provider:                str = "groq"
    whisper_model:                  str = "base"
    whisper_max_duration_seconds:   int = 30

    # ── NLP ───────────────────────────────────────────────────────────────
    nlp_model_path:    str = "models/nlp/v1"
    nlp_model_version: str = "v1_distilbert"

    # ── App / media ───────────────────────────────────────────────────────
    demo_scenario: str = "vadodara_flood"
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
    def social_hashtag_list(self) -> list[str]:
        return [h.strip() for h in self.social_hashtags.split(",")]

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
