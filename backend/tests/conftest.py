"""Shared pytest configuration (Phase 17, §40–41).

* async test support via pytest-asyncio (auto mode — configured in pytest.ini)
* `run()` helper: fresh event loop + asyncpg pool disposal (pooled connections
  are bound to the loop that created them)
* opt-in live smoke tests: anything marked `@pytest.mark.external` is SKIPPED
  unless pytest is invoked with `--run-external` (mocked by default, §41)
"""
from __future__ import annotations

import asyncio
import os

import pytest

# ── Test database isolation ────────────────────────────────────────────────
# The suite used to inherit the application's DATABASE_URL, so every test run
# wrote zones, reports and incidents into the same database the running app
# serves. That is how "Test Zone <hash>" rows ended up in /api/zones and could
# even be selected as the primary zone.
#
# Point the suite at its own database before any app module is imported:
# app.core.config.get_settings() is lru_cached and app.core.database builds its
# engine at import time, so the variable must be set here rather than inside a
# fixture. Nothing above imports app code, which is what makes this safe.
#
# Override with AEGIS_TEST_DATABASE_URL if you need a different target.
_TEST_DATABASE_URL = os.environ.get(
    "AEGIS_TEST_DATABASE_URL",
    "postgresql+asyncpg://aegisai:aegisai_secret@localhost:5433/aegisai_test",
)
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
# Redis is optional for the suite; point it at the same instance but keep the
# app's value if one is already set.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


def pytest_addoption(parser):
    parser.addoption(
        "--run-external",
        action="store_true",
        default=False,
        help="run @pytest.mark.external live-provider smoke tests",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-external"):
        return
    skip_external = pytest.mark.skip(reason="live external call — opt in with --run-external")
    for item in items:
        if "external" in item.keywords:
            item.add_marker(skip_external)


def run(coro):
    """Run a coroutine in a fresh event loop, clearing the asyncpg pool
    first (pooled connections are bound to the previous loop)."""
    from app.core.database import engine

    async def _wrap():
        await engine.dispose()
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_wrap())


@pytest.fixture(scope="session", autouse=True)
def _database_schema() -> None:
    """Create extensions, schema and seed data once per test session.

    The app lifespan normally does this, but the module-level engine pools
    asyncpg connections and every TestClient request runs in its own event
    loop, so pooled connections cannot cross loops and the lifespan bootstrap
    dies with "got Future attached to a different loop". Under uvicorn there is
    a single loop for the whole process, so this is a test-harness constraint
    only. Bootstrapping here — one loop, pool disposed afterwards — gives the
    whole session one shared schema.
    """
    from app.main import _ensure_schema

    run(_ensure_schema())
