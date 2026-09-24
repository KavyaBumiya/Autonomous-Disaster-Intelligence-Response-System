import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models so Alembic can detect them
from app.core.database import Base
import app.models  # noqa: F401 — registers all ORM models

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    import os
    db_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "ssl=" not in db_url and "sslmode=" not in db_url:
        host_part = db_url.split("@", 1)[-1].split("/", 1)[0]
        host = host_part.split(":", 1)[0]
        if host not in {"localhost", "127.0.0.1", "db", "postgres"}:
            db_url = f"{db_url}{'&' if '?' in db_url else '?'}ssl=require"
    connectable = create_async_engine(db_url)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
