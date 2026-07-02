"""Audit trail for admin write actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write(
    session: AsyncSession,
    *,
    admin_id: int | None,
    action: str,
    entity: str,
    entity_id: Any,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before=before,
            after=after,
            ip=ip,
        )
    )
