"""Block until the database has been migrated, then exit 0.

The worker service starts alongside the API, which owns `alembic upgrade head`. Without
this the worker races it: arq comes up, the first cron touches a table that does not exist
yet, and the process dies — repeatedly, with a stack trace that points at the worker for a
problem that belongs to the API's boot order.

Waiting is bounded. If the schema never appears the exit is non-zero, Railway restarts the
service, and the log says which of the two things went wrong — nothing to migrate, or
nothing to connect to.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.db import SessionFactory
from app.core.logging import configure_logging, log
from sqlalchemy import text

TIMEOUT_SECONDS = 180
POLL_SECONDS = 3


async def _schema_ready() -> bool:
    """True once alembic has stamped a revision — i.e. the migration finished."""
    async with SessionFactory() as session:
        stamped = await session.scalar(
            text("SELECT count(*) FROM information_schema.tables "
                 "WHERE table_name = 'alembic_version'")
        )
        if not stamped:
            return False
        # A stamped-but-empty table means alembic created it and then failed, which is
        # not "ready" — the tables the crons need may still be missing.
        return bool(await session.scalar(text("SELECT count(*) FROM alembic_version")))


async def main() -> int:
    configure_logging()
    waited = 0
    last_error: str | None = None
    while waited < TIMEOUT_SECONDS:
        try:
            if await _schema_ready():
                log.info("worker.schema_ready", waited_seconds=waited)
                return 0
            last_error = "database reachable, no alembic revision stamped yet"
        except Exception as exc:  # not up yet, or credentials wrong — both look like this
            last_error = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    log.error("worker.schema_wait_timeout", waited_seconds=waited, last_error=last_error)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
