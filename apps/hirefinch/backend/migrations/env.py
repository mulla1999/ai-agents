"""Alembic environment: async engine, URL from HIREFINCH_DATABASE_URL (SQLite under data_dir by default)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from hirefinch.config import Settings
from hirefinch.db import Base, create_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def run_migrations_offline() -> None:
    url = _settings().db_url
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    # Batch mode lets ALTER TABLE migrations work on SQLite too.
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = _settings().db_url
    # SQLite batch migrations rebuild tables; the app's engine enforces foreign keys, which would block
    # the rebuild. A plain engine leaves them off for the migration only.
    engine = create_async_engine(url) if url.startswith("sqlite") else create_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
