"""Idempotent seed: tariffs, locations, FAQ, app settings, owner admin, dev fixtures.

Run: python -m scripts.seed   (safe to run repeatedly)
"""

from __future__ import annotations

import asyncio
import secrets

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.logging import configure_logging, log
from app.core.security import hash_password
from app.models import (
    AdminUser,
    AppSetting,
    Connection,
    FaqItem,
    Location,
    Tariff,
    User,
)
from app.models.base import Base  # noqa: F401  (ensure metadata import)
from app.seed.data import FAQ, LOCATIONS, TARIFFS, default_settings
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_tariffs(session: AsyncSession) -> None:
    for t in TARIFFS:
        stmt = insert(Tariff).values(**t)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "name": stmt.excluded.name,
                "kind": stmt.excluded.kind,
                "duration_minutes": stmt.excluded.duration_minutes,
                "price_usd": stmt.excluded.price_usd,
                "max_per_user": stmt.excluded.max_per_user,
                "max_user_swaps": stmt.excluded.max_user_swaps,
                "auto_issue": stmt.excluded.auto_issue,
                "sort_order": stmt.excluded.sort_order,
                "description": stmt.excluded.description,
            },
        )
        await session.execute(stmt)


async def seed_locations(session: AsyncSession) -> None:
    for city, state, sort in LOCATIONS:
        stmt = insert(Location).values(city=city, state_code=state, sort_order=sort)
        stmt = stmt.on_conflict_do_nothing(index_elements=["city", "state_code"])
        await session.execute(stmt)


async def seed_faq(session: AsyncSession) -> None:
    count = await session.scalar(select(func.count()).select_from(FaqItem))
    if count:
        return  # FAQ is operator-editable; only seed an empty table
    for category, question, answer, sort in FAQ:
        session.add(
            FaqItem(category=category, question=question, answer=answer, sort_order=sort)
        )


async def seed_settings(session: AsyncSession) -> None:
    for key, value in default_settings().items():
        stmt = insert(AppSetting).values(key=key, value=value)
        stmt = stmt.on_conflict_do_nothing(index_elements=["key"])
        await session.execute(stmt)


async def seed_admin(session: AsyncSession) -> None:
    if not settings.seed_admin_password:
        log.warning("seed.admin_skipped", reason="SEED_ADMIN_PASSWORD not set")
        return
    existing = await session.scalar(
        select(AdminUser).where(AdminUser.email == settings.seed_admin_email)
    )
    if existing:
        return
    session.add(
        AdminUser(
            email=settings.seed_admin_email,
            password_hash=hash_password(settings.seed_admin_password),
            display_name="Owner",
            role="owner",
        )
    )


async def seed_dev_fixtures(session: AsyncSession) -> None:
    if settings.is_prod or not settings.seed_dev_fixtures:
        return
    existing = await session.scalar(select(func.count()).select_from(Connection))
    if existing:
        return
    carriers = ["T-Mobile", "Verizon", "AT&T"]
    locations = (await session.execute(select(Location))).scalars().all()
    for i, loc in enumerate(locations):
        for j in range(2):  # 2 connections per city
            session.add(
                Connection(
                    iproxy_connection_id=f"dev-{loc.state_code}-{j}",
                    name=f"{loc.city} #{j + 1}",
                    location_id=loc.id,
                    carrier=carriers[(i + j) % 3],
                    tier="stable" if j == 0 else "standard",
                    is_sellable=True,
                    online_status="online",
                )
            )
    session.add(
        User(
            tg_user_id=100001,
            tg_username="dev_user",
            first_name="Dev",
            lang="en",
            referral_code=secrets.token_hex(4).upper(),
        )
    )


async def main() -> None:
    configure_logging()
    async with SessionFactory() as session:
        await seed_settings(session)
        await seed_tariffs(session)
        await seed_locations(session)
        await seed_faq(session)
        await seed_admin(session)
        await session.flush()
        await seed_dev_fixtures(session)
        await session.commit()
    log.info("seed.done")


if __name__ == "__main__":
    asyncio.run(main())
