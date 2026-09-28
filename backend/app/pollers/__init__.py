"""
Shared poller helpers.

`CancelledError` handling for APScheduler jobs.

APScheduler runs each poller as a task on the application event loop. When the
app shuts down, `scheduler.shutdown()` cancels any in-flight job, which raises
`CancelledError` inside whatever the poller was awaiting — typically an httpx
read or a Redis GET. Two properties matter and are easy to get wrong:

  * `CancelledError` inherits from `BaseException`, not `Exception`, so a
    broad `except Exception` will NOT catch it. That is correct and deliberate:
    cancellation must never be converted into a provider failure.
  * Swallowing it would break task-cancellation semantics, so it is always
    re-raised after being logged.

Log it at info as an expected shutdown event, so a normal deploy does not leave
a provider-failure ERROR in the logs.
"""
from __future__ import annotations

import asyncio

import structlog

logger = structlog.get_logger()


def log_poller_cancelled(job_name: str) -> None:
    """Record a poller cancelled by application shutdown, at info level.

    Call from a `except asyncio.CancelledError:` branch immediately before
    re-raising. The caller must re-raise — this function never consumes the
    cancellation.
    """
    logger.info("poller_cancelled_during_shutdown", job=job_name)
