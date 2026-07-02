"""Test configuration.

Sets deterministic env BEFORE importing the app, then provides a Postgres-backed
schema fixture. Postgres tests skip automatically if no server is reachable, so the
pure-unit suite (security primitives) still runs anywhere.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

# --- env must be set before any `app.*` import (settings are cached) -------
os.environ.setdefault("ENV", "local")
os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN-aaaaaaaaaaaaaaaaaaaaaaaa")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-secret-please-change-32bytes-minimum!!")
os.environ.setdefault("CREDENTIALS_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SEED_ADMIN_PASSWORD", "test-owner-pw-123")

from urllib.parse import urlsplit  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB_NAME = "bm_usa_proxy_test"


def _test_db_url() -> str:
    parts = urlsplit(settings.database_url)
    return settings.database_url.replace(parts.path, f"/{TEST_DB_NAME}")


async def _ensure_test_db() -> bool:
    import asyncpg  # local import so import-time never fails

    parts = urlsplit(settings.database_url)
    try:
        conn = await asyncpg.connect(
            host=parts.hostname or "localhost",
            port=parts.port or 5432,
            user=parts.username or "bm",
            password=parts.password or "bm",
            database="postgres",
        )
    except Exception:
        return False
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()
    return True


@pytest_asyncio.fixture
async def engine():
    if not await _ensure_test_db():
        pytest.skip("Postgres not reachable — skipping DB-backed tests")
    eng = create_async_engine(_test_db_url())
    async with eng.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
