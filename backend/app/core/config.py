"""
Central configuration loaded from environment variables via pydantic-settings.
All settings are read once at startup and available via `get_settings()`.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="")

    # ── Database ──────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://aegisai:aegisai_secret@db:5432/aegisai"

    # ── Redis ─────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Auth ──────────────────────────────────────────────────
    jwt_secret: str = "change_this_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── External APIs ─────────────────────────────────────────
    usgs_api_base: str = "https://earthquake.usgs.gov/fdsnws/event/1"
    twitter_bearer_token: str = ""
    mapbox_access_token: str = ""
    nominatim_user_agent: str = "AegisAI/1.0"

    # ── Social media ──────────────────────────────────────────
    social_hashtags: str = "#flood,#earthquake,#cyclone,#fire,#disaster,#SOS,#rescue"
    social_poll_interval_seconds: int = 60
    social_provider: str = "twitter"  # "twitter" | "mastodon"

    # ── Whisper ───────────────────────────────────────────────
    whisper_model: str = "base"
    whisper_max_duration_seconds: int = 30

    # ── NLP ───────────────────────────────────────────────────
    nlp_model_path: str = "models/nlp/v1"
    nlp_model_version: str = "v1_distilbert"

    # ── App ───────────────────────────────────────────────────
    demo_scenario: str = "vadodara_flood"
    media_dir: str = "media/audio"

    # ── Production validation ───────────────────────────────
    def model_validate_prod(self) -> None:
        """Validate required production environment variables."""
        required = [
            self.jwt_secret,
            self.twitter_bearer_token,
            self.mapbox_access_token,
        ]
        missing = [field for field, val in required.__class__.__dict__.items() if not val]
        if missing:
            raise ValueError(f"Missing required environment variables: {missing}")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Validate in production
    if not settings.jwt_secret or settings.jwt_secret == "change_this_in_production":
        raise ValueError("JWT secret must be set for production deployment")
    return settings
