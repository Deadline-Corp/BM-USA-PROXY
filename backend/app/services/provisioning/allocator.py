"""Atomic pool allocation — INVARIANT #2 (one phone, one sale).

FOR UPDATE ... SKIP LOCKED picks a free, online, sellable connection matching the
requested city/carrier; the partial unique index on accesses is the backstop.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ALLOC_SQL = text(
    """
    SELECT c.id, c.iproxy_connection_id
    FROM connections c
    WHERE c.is_sellable AND c.online_status = 'online'
      AND (CAST(:location_id AS bigint) IS NULL OR c.location_id = CAST(:location_id AS bigint))
      AND (CAST(:carrier AS text) IS NULL OR c.carrier = CAST(:carrier AS text))
      AND (CAST(:exclude_id AS bigint) IS NULL OR c.id <> CAST(:exclude_id AS bigint))
      AND NOT EXISTS (
        SELECT 1 FROM accesses a
        WHERE a.connection_id = c.id
          AND a.status IN ('provisioning','active','expiring')
      )
    ORDER BY (c.tier = 'stable') DESC, c.last_online_at DESC NULLS LAST
    FOR UPDATE OF c SKIP LOCKED
    LIMIT 1
    """
)


async def allocate(
    session: AsyncSession,
    *,
    location_id: int | None = None,
    carrier: str | None = None,
    exclude_id: int | None = None,
) -> tuple[int, str] | None:
    """Return (connection_id, iproxy_connection_id) locked for this txn, or None."""
    row = (
        await session.execute(
            _ALLOC_SQL,
            {
                "location_id": location_id,
                "carrier": carrier,
                "exclude_id": exclude_id,
            },
        )
    ).first()
    return (row[0], row[1]) if row else None


async def count_available(
    session: AsyncSession, *, location_id: int | None = None, carrier: str | None = None
) -> int:
    row = await session.execute(
        text(
            """
            SELECT count(*) FROM connections c
            WHERE c.is_sellable AND c.online_status = 'online'
              AND (CAST(:location_id AS bigint) IS NULL OR c.location_id = CAST(:location_id AS bigint))
              AND (CAST(:carrier AS text) IS NULL OR c.carrier = CAST(:carrier AS text))
              AND NOT EXISTS (
                SELECT 1 FROM accesses a
                WHERE a.connection_id = c.id
                  AND a.status IN ('provisioning','active','expiring'))
            """
        ),
        {"location_id": location_id, "carrier": carrier},
    )
    return int(row.scalar_one())
