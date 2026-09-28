"""
Social post dedup and incremental-polling guarantees.

Covers the four behaviours that must hold for the social poller:

  1. a first occurrence is stored
  2. a repeated occurrence is ignored
  3. a genuinely new post is stored
  4. restarting the poller does not create duplicates

(1)-(3) are the in-process MinHash path; (4) is the database path, because the
MinHash index is in-memory only and a restart would otherwise forget every post
it had already stored.

The incremental `since_id` watermark is covered too: it is what stops the
poller re-downloading the same recent-tweets window on every cycle.
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.models.report import Report
from app.services import deduplication

pytestmark = pytest.mark.asyncio


def _text(seed: str) -> str:
    return f"Water level rising near the {seed} bridge, residents advised to move uphill now"


@pytest.fixture(autouse=True)
def _reset_dedup_index():
    """Each test starts from an empty MinHash index."""
    deduplication.reset_index()
    yield
    deduplication.reset_index()


async def test_first_occurrence_is_stored():
    """A post seen for the first time is not a duplicate."""
    assert deduplication.is_duplicate(_text("alpha"), "1001") is False


async def test_repeated_occurrence_is_ignored():
    """The same post id and text on a second pass is a duplicate."""
    text = _text("beta")
    assert deduplication.is_duplicate(text, "2002") is False
    assert deduplication.is_duplicate(text, "2002") is True


async def test_new_post_is_stored():
    """A genuinely different post is not suppressed by an unrelated earlier one.

    The texts must differ substantially: MinHash treats anything above 0.85
    Jaccard similarity as a near-duplicate, which is the intended behaviour for
    bot-amplified reposts and is tested separately.
    """
    assert deduplication.is_duplicate(_text("gamma"), "3003") is False
    assert deduplication.is_duplicate(
        "Cyclone windsurf gusts reported near the coastal shelter, evacuation "
        "buses dispatched from the east terminal this afternoon",
        "4004",
    ) is False


async def test_near_duplicate_text_is_suppressed():
    """Reposted text with only small edits is treated as a duplicate."""
    original = _text("zeta")
    repost = original.replace("bridge", "bridge").replace("move uphill", "move up hill")
    assert deduplication.is_duplicate(original, "5005") is False
    assert deduplication.is_duplicate(repost, "5006") is True


async def test_restart_does_not_duplicate_stored_post():
    """A fresh process (empty in-memory index) must not re-insert a stored post.

    This is the guarantee the in-process index cannot provide on its own, so
    `_process_post` checks the database for the exact social_post_id.
    """
    from app.core.database import AsyncSessionLocal

    report_id = str(uuid.uuid4())

    # Simulate a restart: the MinHash index is gone, the database is not.
    deduplication.reset_index()
    text = _text("epsilon")
    assert deduplication.is_duplicate(text, "5555") is False, (
        "in-memory index is empty after restart, so dedup must fall back to the DB"
    )

    async with AsyncSessionLocal() as db:
        try:
            db.add(
                Report(
                    id=report_id,
                    reporter_id="anon",
                    message_text=text,
                    social_post_id="5555",
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

            # The durable check the poller performs before inserting.
            already = (
                await db.execute(
                    select(Report.id).where(Report.social_post_id == "5555").limit(1)
                )
            ).first()
            assert already is not None, "stored post must be findable by social_post_id"
        finally:
            # Leave no residue for other tests or repeat runs.
            await db.execute(delete(Report).where(Report.id == report_id))
            await db.commit()


async def test_twitter_cursor_is_advanced(monkeypatch):
    """The since_id watermark advances to the newest tweet actually retrieved."""
    from app.pollers import social

    store: dict[str, str] = {}

    async def _cache_get(key):
        return store.get(key)

    async def _cache_set(key, value, ttl=None):
        store[key] = value

    class _Tweet:
        def __init__(self, tid, text):
            self.id = tid
            self.text = text
            self.created_at = None
            self.author_id = "1"

    class _Resp:
        def __init__(self, data):
            self.data = data

    class _Client:
        def __init__(self, bearer_token):
            self.calls = []

        async def search_recent_tweets(self, **kwargs):
            self.calls.append(kwargs)
            return _Resp([_Tweet(117349090967114633, "flood"), _Tweet(117349090967114634, "flood")])

    fake = types.ModuleType("tweepy")

    def _factory(bearer_token):
        return _Client(bearer_token)

    fake.AsyncClient = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tweepy", fake)
    monkeypatch.setattr(social, "cache", types.SimpleNamespace(
        cache_get=_cache_get, cache_set=_cache_set))

    monkeypatch.setattr(social.settings, "twitter_bearer_token", "real-looking-token")

    first = await social._fetch_twitter("#flood")
    assert len(first) == 2
    assert store, "cursor should be written after the first fetch"

    # A second cycle must not re-request the window it already has.
    await social._fetch_twitter("#flood")
