import logging
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Google Maps
    GOOGLE_MAPS_API_KEY: str

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_TTL_SECONDS: int = 1800

    # Solver
    MAX_OPTIMIZATION_SECONDS: int = 10
    MAX_STOPS_PER_ROUTE: int = 25

    # App
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Phase 2 — Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Phase 2 — Re-routing thresholds
    DELAY_THRESHOLD_MINUTES: int = 5
    TRAFFIC_INCREASE_RATIO: float = 1.20
    MIN_REROUTE_INTERVAL_SECONDS: int = 300
    DRIVER_STATE_TTL_SECONDS: int = 43200

    # Phase 2 — Push notifications
    FIREBASE_SERVER_KEY: str = ""


settings = Settings()


def configure_logging() -> None:
    """Configure root logger level and format from settings."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
