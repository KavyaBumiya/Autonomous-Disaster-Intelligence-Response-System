"""
Social media poller — Twitter v2 + Mastodon fallback.
Runs every SOCIAL_POLL_INTERVAL_SECONDS (default 60s).
Classifies posts via NLP, deduplicates, stores informative ones as reports.
"""
import hashlib
import uuid
from datetime import datetime, timezone

import structlog

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.report import Report
from app.models.social_poll import SocialMediaPoll
from app.services import nlp_service, deduplication, gis_service
from app.services.geocoding import geocode

logger = structlog.get_logger()
settings = get_settings()


def _anon_reporter_id(post_id: str) -> str:
    return hashlib.sha256(f"social:{post_id}".encode()).hexdigest()[:32]


# ── Twitter ───────────────────────────────────────────────────

async def _fetch_twitter(hashtag: str) -> list[dict]:
    """Fetch recent tweets for a hashtag using Twitter API v2."""
    if not settings.twitter_bearer_token:
        return []
    try:
        import tweepy
        client = tweepy.AsyncClient(bearer_token=settings.twitter_bearer_token)
        query = f"{hashtag} -is:retweet lang:en"
        response = await client.search_recent_tweets(
            query=query,
            max_results=10,
            tweet_fields=["id", "text", "created_at", "geo", "author_id"],
            expansions=["geo.place_id"],
        )
        if not response.data:
            return []
        return [
            {
                "id": str(tweet.id),
                "text": tweet.text,
                "created_at": tweet.created_at,
                "source": "twitter_v2",
            }
            for tweet in response.data
        ]
    except Exception as e:
        logger.warning("Twitter fetch failed", hashtag=hashtag, error=str(e))
        return []


async def _fetch_mastodon(hashtag: str) -> list[dict]:
    """Fetch recent public toots for a hashtag from mastodon.social."""
    import httpx
    tag = hashtag.lstrip("#")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://mastodon.social/api/v1/timelines/tag/{tag}",
                params={"limit": 10},
            )
            resp.raise_for_status()
            toots = resp.json()
            return [
                {
                    "id": str(t["id"]),
                    "text": t.get("content", ""),
                    "created_at": t.get("created_at"),
                    "source": "mastodon",
                }
                for t in toots
            ]
    except Exception as e:
        logger.warning("Mastodon fetch failed", hashtag=hashtag, error=str(e))
        return []


async def _process_post(post: dict, db) -> bool:
    """
    Process a single social post:
    - Deduplicate
    - NLP classify
    - Geocode
    - Store as report
    Returns True if stored.
    """
    text = post.get("text", "")
    # Strip HTML tags (Mastodon returns HTML)
    import re
    text = re.sub(r"<[^>]+>", " ", text).strip()

    if not text or len(text) < 20:
        return False

    post_id = post["id"]

    # Deduplicate
    if deduplication.is_duplicate(text, post_id):
        return False

    # NLP classification
    nlp_result = await nlp_service.process(text)

    # Drop non-informative posts
    if not nlp_result.get("informative_flag"):
        return False

    # Geocode fallback — use NLP location if available
    lat = nlp_result.get("lat")
    lng = nlp_result.get("lng")

    # Determine zone (simplified: will be zone-matched in orchestrator)
    report = Report(
        id=str(uuid.uuid4()),
        reporter_id=_anon_reporter_id(post_id),
        message_text=text[:1000],
        disaster_type=nlp_result.get("disaster_type"),
        nlp_confidence=nlp_result.get("nlp_confidence"),
        informative_flag=nlp_result.get("informative_flag"),
        language_code=nlp_result.get("language_code"),
        location_string=nlp_result.get("location_string"),
        lat=lat,
        lng=lng,
        geocoding_confidence=nlp_result.get("geocoding_confidence"),
        source=post.get("source", "social_media"),
        social_post_id=post_id,
        nlp_model_version=nlp_result.get("nlp_model_version", "v0_keyword"),
        trust_score=None,  # set by Verification Agent
        suppressed=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(report)
    await db.flush()
    await gis_service.set_report_geometry(db, report.id, report.lat, report.lng)
    return True


async def poll_social() -> None:
    """Main social media poll cycle — iterates all configured hashtags."""
    provider = settings.social_provider
    hashtags = settings.social_hashtag_list

    async with AsyncSessionLocal() as db:
        for hashtag in hashtags:
            posts = []
            if provider == "mastodon":
                posts = await _fetch_mastodon(hashtag)
            else:
                posts = await _fetch_twitter(hashtag)
                if not posts:  # fallback to Mastodon
                    posts = await _fetch_mastodon(hashtag)

            fetched = len(posts)
            stored = 0
            filtered = 0

            for post in posts:
                try:
                    ok = await _process_post(post, db)
                    if ok:
                        stored += 1
                    else:
                        filtered += 1
                except Exception as e:
                    logger.warning("Social post processing failed", error=str(e))
                    filtered += 1

            # Log poll summary
            poll_log = SocialMediaPoll(
                id=str(uuid.uuid4()),
                hashtag=hashtag,
                api_source=provider,
                posts_fetched=fetched,
                posts_stored=stored,
                posts_filtered=filtered,
                polled_at=datetime.now(timezone.utc),
            )
            db.add(poll_log)

        await db.commit()
        logger.info("Social poll complete", provider=provider, hashtags=len(hashtags))
