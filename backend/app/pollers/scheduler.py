"""
Apscheduler setup — starts all background pollers on app startup.
Pollers are imported lazily to avoid blocking app startup
when optional dependencies (spacy, etc.) are unavailable.
"""
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_scheduler: AsyncIOScheduler | None = None

# APScheduler's default misfire_grace_time is 1 second. The social poller runs
# 7 hashtags x (1 Twitter + 1 Mastodon call) at a 10s timeout each, plus spaCy
# and geocoding per post, so a single cycle can legitimately overrun its 60s
# interval. With a 1s grace window every later fire time is then "missed" and
# skipped outright, and coalesce=True means there is no catch-up run either --
# the feed looks live but has silently frozen. 300s absorbs a bad cycle.
JOB_DEFAULTS = {
    "misfire_grace_time": 300,
    "coalesce": True,
    "max_instances": 1,
}


def _add_job(fn, *, trigger: IntervalTrigger, job_id: str, name: str) -> bool:
    """Register a poller, or report it as dropped and keep the rest running.

    A poller whose import fails (missing spacy model, absent optional dep) must
    cost one data feed, not the whole process: `start_scheduler` is called from
    the lifespan, so an unhandled ImportError here means the port never binds
    and there is no dashboard, no API and no pollers at all.
    """
    try:
        _scheduler.add_job(
            fn,
            trigger=trigger,
            id=job_id,
            name=name,
            replace_existing=True,
            max_instances=1,
            # APScheduler 3.x defaults a trigger's first run to
            # `now + interval` when no start_date is given, so a cold boot
            # leaves every panel empty for one full interval (10 min for EONET,
            # 5 min for weather). Fire immediately, then on the interval.
            next_run_time=datetime.now(timezone.utc),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - one bad feed must not kill boot
        logger.warning(
            "poller_registration_failed",
            poller=job_id,
            error=type(exc).__name__,
            detail=str(exc)[:200],
        )
        return False


async def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(job_defaults=JOB_DEFAULTS)

    registered: list[str] = []
    dropped: list[str] = []

    def register(fn, *, trigger: IntervalTrigger, job_id: str, name: str) -> None:
        (registered if _add_job(fn, trigger=trigger, job_id=job_id, name=name)
         else dropped).append(job_id)

    # Pollers are imported one at a time, each guarded, so a missing optional
    # dependency removes exactly one feed.
    try:
        from app.pollers.weather import poll_weather  # type: ignore
        register(poll_weather, trigger=IntervalTrigger(minutes=5),
                 job_id="weather_poller", name="Open-Meteo weather poller")
    except Exception as exc:  # noqa: BLE001
        logger.warning("poller_import_failed", poller="weather",
                       error=type(exc).__name__, detail=str(exc)[:200])
        dropped.append("weather_poller")

    try:
        from app.pollers.seismic import poll_seismic  # type: ignore
        register(poll_seismic, trigger=IntervalTrigger(minutes=2),
                 job_id="seismic_poller", name="USGS seismic poller")
    except Exception as exc:  # noqa: BLE001
        logger.warning("poller_import_failed", poller="seismic",
                       error=type(exc).__name__, detail=str(exc)[:200])
        dropped.append("seismic_poller")

    if settings.social_enabled:
        try:
            from app.pollers.social import poll_social  # type: ignore
            register(poll_social,
                     trigger=IntervalTrigger(seconds=settings.social_poll_interval_seconds),
                     job_id="social_poller", name="Social media poller")
        except Exception as exc:  # noqa: BLE001
            logger.warning("poller_import_failed", poller="social",
                           error=type(exc).__name__, detail=str(exc)[:200])
            dropped.append("social_poller")

    try:
        from app.pollers.eonet import poll_eonet  # type: ignore
        register(poll_eonet, trigger=IntervalTrigger(minutes=settings.eonet_poll_interval_minutes),
                 job_id="eonet_poller", name="NASA EONET natural-event poller")
    except Exception as exc:  # noqa: BLE001
        logger.warning("poller_import_failed", poller="eonet",
                       error=type(exc).__name__, detail=str(exc)[:200])
        dropped.append("eonet_poller")

    _scheduler.start()
    logger.info(
        "Pollers scheduled",
        weather_interval="5min",
        seismic_interval="2min",
        social_interval=(
            f"{settings.social_poll_interval_seconds}s" if settings.social_enabled else "disabled"
        ),
        eonet_interval=f"{settings.eonet_poll_interval_minutes}min",
        registered=registered,
        dropped=dropped,
    )


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        # wait=True lets an in-flight poller finish instead of cancelling it
        # mid-request. Every connector has a hard timeout, so the wait is
        # bounded; without it APScheduler cancels the job, the CancelledError
        # surfaces from inside an httpx read, and the executor logs a spurious
        # provider-failure ERROR on every ordinary shutdown.
        _scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")
