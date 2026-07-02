"""app_settings read/write helpers (referral params, invoice TTL, ToS, notify texts)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting


async def get(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(AppSetting, key)
    return row.value if row is not None else default


async def set_value(
    session: AsyncSession, key: str, value: Any, *, admin_id: int | None = None
) -> None:
    stmt = insert(AppSetting).values(key=key, value=value, updated_by=admin_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value, "updated_by": admin_id},
    )
    await session.execute(stmt)
