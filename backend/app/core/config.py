"""
AEGIS-AI — Central configuration
==================================
All settings are loaded from environment variables (server-side .env).
The GROQ_API_KEY is loaded here and never serialised into any HTTP response.
"""
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="")

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://aegisai:aegisai_secret@db:5432/aegisai"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        """Normalise Render/Heroku postgres:// URLs to asyncpg dialect."""
        if isinstance(v, str):
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+asyncpg://", 1)
            if v.startswith("postgresql://") and "+asyncpg" not in v:
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

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
    #   qwen/qwen3.8-27b        — primary, produces full responses
    #   openai/gpt-oss-20b      — available but returns empty completions
    #   openai/gpt-oss-120b     — available but returns empty completions
    # DO NOT use llama-3.x or mixtral — not available on this key's tier.
    groq_model:   str = "qwen/qwen3.8-27b"

    # ── External data APIs ────────────────────────────────────────────────
    usgs_api_base:       str = "https://earthquake.usgs.gov/fdsnws/event/1"
    twitter_bearer_token: str = ""
    mapbox_access_token: str = ""
    nominatim_user_agent: str = "AegisAI/1.0"

    # ── Social media polling ──────────────────────────────────────────────
    social_hashtags:              str = "#flood,#earthquake,#cyclone,#fire,#disaster,#SOS,#rescue"
    social_poll_interval_seconds: int = 60
    social_provider:              str = "twitter"   # "twitter" | "mastodon"

    # ── Whisper STT ───────────────────────────────────────────────────────
    whisper_model:                  str = "base"
    whisper_max_duration_seconds:   int = 30

    # ── NLP ───────────────────────────────────────────────────────────────
    nlp_model_path:    str = "models/nlp/v1"
    nlp_model_version: str = "v1_distilbert"

    # ── App / media ───────────────────────────────────────────────────────
    demo_scenario: str = "vadodara_flood"
    media_dir:     str = "media/audio"

    @property
    def social_hashtag_list(self) -> list[str]:
        return [h.strip() for h in self.social_hashtags.split(",")]

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
