"""
Demo data seeder.
Run: python seed.py           — seeds users + Vadodara flood fixture reports
Run: python seed.py --reset   — drops all data first
"""
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aegisai:aegisai_secret@localhost:5432/aegisai")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def seed_users(db: AsyncSession) -> None:
    from app.auth.jwt import hash_password

    users = [
        {"id": str(uuid.uuid4()), "username": "commander@aegis.demo", "role": "commander", "password": "demo123"},
        {"id": str(uuid.uuid4()), "username": "responder@aegis.demo",  "role": "responder",  "password": "demo123"},
        {"id": str(uuid.uuid4()), "username": "analyst@aegis.demo",    "role": "analyst",    "password": "demo123"},
    ]

    for u in users:
        await db.execute(text("""
            INSERT INTO users (id, username, password_hash, role, created_at)
            VALUES (:id, :username, :password_hash, :role, NOW())
            ON CONFLICT (username) DO NOTHING
        """), {
            "id": u["id"],
            "username": u["username"],
            "password_hash": hash_password(u["password"]),
            "role": u["role"],
        })
    print("  ✓ Demo users seeded (commander / responder / analyst)")


async def seed_fixtures(db: AsyncSession) -> None:
    fixtures_path = Path(__file__).parent / "fixtures" / "vadodara_flood.json"
    if not fixtures_path.exists():
        print("  ⚠ Fixture file not found, skipping report seed")
        return

    with open(fixtures_path) as f:
        data = json.load(f)

    base_time = datetime.now(timezone.utc) - timedelta(minutes=45)

    # Seed zones first
    zones = data.get("zones", [])
    for z in zones:
        await db.execute(text("""
            INSERT INTO zones (id, name, centroid_lat, centroid_lng, radius_meters, created_at, updated_at)
            VALUES (:id, :name, :lat, :lng, :radius, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """), {
            "id": z["id"], "name": z["name"], "lat": z["centroid_lat"],
            "lng": z["centroid_lng"], "radius": z.get("radius_meters", 500.0)
        })

    # Seed resources
    resources = data.get("resources", [])
    for r in resources:
        await db.execute(text("""
            INSERT INTO resources (id, name, resource_type, capacity, current_load, lat, lng, available)
            VALUES (:id, :name, :rtype, :capacity, 0, :lat, :lng, true)
            ON CONFLICT (id) DO NOTHING
        """), {
            "id": r["id"], "name": r["name"], "rtype": r.get("resource_type", "supply"),
            "capacity": r.get("capacity", 1), "lat": r.get("lat"), "lng": r.get("lng")
        })

    # Seed reports
    reports = data.get("reports", [])
    for i, rep in enumerate(reports):
        created = base_time + timedelta(minutes=i * 2)
        await db.execute(text("""
            INSERT INTO reports (
                id, zone_id, reporter_id, message_text, transcript, location_string,
                lat, lng, disaster_type, nlp_confidence, informative_flag,
                language_code, source, trust_score, suppressed, social_post_id,
                nlp_model_version, created_at, updated_at
            ) VALUES (
                :id, :zone_id, :reporter_id, :message_text, :transcript, :location_string,
                :lat, :lng, :disaster_type, :nlp_confidence, :informative_flag,
                :language_code, :source, :trust_score, :suppressed, :social_post_id,
                :nlp_model_version, :created_at, :created_at
            ) ON CONFLICT (id) DO NOTHING
        """), {
            "id": rep["id"],
            "zone_id": rep.get("zone_id"),
            "reporter_id": rep.get("reporter_id", f"seed_{i}"),
            "message_text": rep.get("message_text"),
            "transcript": rep.get("transcript"),
            "location_string": rep.get("location_string"),
            "lat": rep.get("lat"),
            "lng": rep.get("lng"),
            "disaster_type": rep.get("disaster_type", "flood"),
            "nlp_confidence": rep.get("nlp_confidence", 0.82),
            "informative_flag": rep.get("informative_flag", True),
            "language_code": rep.get("language_code", "en"),
            "source": rep.get("source", "citizen_text"),
            "trust_score": rep.get("trust_score"),
            "suppressed": rep.get("suppressed", False),
            "social_post_id": rep.get("social_post_id"),
            "nlp_model_version": rep.get("nlp_model_version", "v0_keyword"),
            "created_at": created,
        })

    print(f"  ✓ {len(reports)} fixture reports seeded (Vadodara flood scenario)")
    print(f"  ✓ {len(zones)} zones seeded")
    print(f"  ✓ {len(resources)} resources seeded")


async def reset(db: AsyncSession) -> None:
    tables = [
        "audio_uploads", "agent_outputs", "actions", "incidents",
        "reports", "zones", "resources", "users",
        "weather_readings", "seismic_events", "social_media_polls",
    ]
    for table in tables:
        await db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    print("  ✓ All tables truncated")


async def main() -> None:
    do_reset = "--reset" in sys.argv
    async with AsyncSessionLocal() as db:
        if do_reset:
            print("Resetting database...")
            await reset(db)
            await db.commit()

        print("Seeding demo data...")
        await seed_users(db)
        await seed_fixtures(db)
        await db.commit()

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
