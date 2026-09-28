"""
Apscheduler setup — starts all background pollers on app startup.
Pollers are imported lazily to avoid blocking app startup
when optional dependencies (spacy, etc.) are unavailable.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_scheduler: AsyncIOScheduler | None = None


async def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler()

    # Import pollers lazily
    from app.pollers.weather import poll_weather  # type: ignore
    from app.pollers.seismic import poll_seismic  # type: ignore
    from app.pollers.eonet import poll_eonet  # type: ignore

    _scheduler.add_job(
        poll_weather,
        trigger=IntervalTrigger(minutes=5),
        id="weather_poller",
        name="OpenWeatherMap poller",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.add_job(
        poll_seismic,
        trigger=IntervalTrigger(minutes=2),
        id="seismic_poller",
        name="USGS seismic poller",
        replace_existing=True,
        max_instances=1,
    )

    if settings.social_enabled:
        _scheduler.add_job(
            poll_social,
            trigger=IntervalTrigger(seconds=settings.social_poll_interval_seconds),
            id="social_poller",
            name="Social media poller",
            replace_existing=True,
            max_instances=1,
        )

    _scheduler.add_job(
        poll_eonet,
        trigger=IntervalTrigger(minutes=settings.eonet_poll_interval_minutes),
        id="eonet_poller",
        name="NASA EONET natural-event poller",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info(
        "Pollers scheduled",
        weather_interval="5min",
        seismic_interval="2min",
        social_interval=(
            f"{settings.social_poll_interval_seconds}s" if settings.social_enabled else "disabled"
        ),
        eonet_interval=f"{settings.eonet_poll_interval_minutes}min",
    )


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
