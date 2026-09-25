"""Shared pytest configuration (Phase 17, §40–41).

* async test support via pytest-asyncio (auto mode — configured in pytest.ini)
* `run()` helper: fresh event loop + asyncpg pool disposal (pooled connections
  are bound to the loop that created them)
* opt-in live smoke tests: anything marked `@pytest.mark.external` is SKIPPED
  unless pytest is invoked with `--run-external` (mocked by default, §41)
"""
from __future__ import annotations

import asyncio

import pytest


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
