"""ARQ job wrappers — thin: open a session, call a service, commit, heartbeat.

The testable logic lives in services (maintenance, referral, payments.processing);
these wrappers wire it to the worker + schedule.
"""

from __future__ import annotations

import contextlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.logging import log
from app.models import Broadcast, Connection, Invoice
from app.services import referral
from app.services.maintenance import expire_invoices, sweep_access_expiries


async def _beat(ctx: dict, name: str) -> None:
    with contextlib.suppress(Exception):
        await ctx["redis"].set(f"worker:alive:{name}", "1", ex=180)


async def expiry_sweeper(ctx: dict) -> dict[str, int]:
    async with SessionFactory() as s:
        result = await sweep_access_expiries(s)
        await s.commit()
    await _beat(ctx, "expiry_sweeper")
    return result


async def invoice_expirer(ctx: dict) -> int:
    async with SessionFactory() as s:
        n = await expire_invoices(s)
        await s.commit()
    await _beat(ctx, "invoice_expirer")
    return n


async def release_referral_holds(ctx: dict) -> int:
    async with SessionFactory() as s:
        n = await referral.release_holds(s)
        await s.commit()
    await _beat(ctx, "release_referral_holds")
    return n


async def send_outbox(ctx: dict) -> dict[str, int] | None:
    from app.bot.factory import get_bot
    from app.bot.notifier import deliver_pending

    bot = get_bot()
    if bot is None:
        return None
    async with SessionFactory() as s:
        result = await deliver_pending(s, bot)
        await s.commit()
    await _beat(ctx, "send_outbox")
    return result


async def reconcile_invoices(ctx: dict) -> int:
    from app.services.payments.base import PaymentEventDTO
    from app.services.payments.processing import ingest_webhook, process_payment_event
    from app.services.payments.registry import get_payment_provider

    prov = get_payment_provider()
    reconciled = 0
    async with SessionFactory() as s:
        invoices = (
            await s.execute(
                select(Invoice).where(Invoice.status.in_(("created", "pending", "confirming")))
            )
        ).scalars().all()
        for inv in invoices:
            with contextlib.suppress(Exception):
                st = await prov.fetch_invoice(inv.provider_invoice_id)
                if st.status != inv.status:
                    dto = PaymentEventDTO(provider_invoice_id=inv.provider_invoice_id,
                                          status=st.status, provider_event_id=None)
                    eid = await ingest_webhook(s, provider=prov.name, raw_body=b'{"src":"recon"}',
                                               signature_valid=True, dto=dto)
                    if eid is not None:
                        await process_payment_event(s, eid)
                        reconciled += 1
        await s.commit()
    await _beat(ctx, "reconcile_invoices")
    return reconciled


async def sync_connections(ctx: dict) -> dict[str, Any]:
    """Mirror iproxy inventory + online status into `connections` (real provider only)."""
    if not settings.feature_real_payments:
        await _beat(ctx, "sync_connections")
        return {"skipped": "mock mode"}

    from app.services.provisioning.iproxy import IproxyClient

    client = IproxyClient()
    upserted = 0
    async with SessionFactory() as s:
        conns = await client.list_connections()
        status_by_id = {str(r.get("id")): r for r in await client.connection_status()}
        for c in conns:
            cid = str(c.get("id") or c.get("connectionId") or "")
            if not cid:
                continue
            st = status_by_id.get(cid, {})
            online = "online" if st.get("online") or st.get("status") == "online" else "offline"
            stmt = insert(Connection).values(
                iproxy_connection_id=cid,
                name=c.get("name") or "",
                online_status=online,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["iproxy_connection_id"],
                set_={"online_status": online, "name": stmt.excluded.name},
            )
            await s.execute(stmt)
            upserted += 1
        await s.commit()
    await _beat(ctx, "sync_connections")
    log.info("iproxy.sync", upserted=upserted)
    return {"upserted": upserted}


async def publish_scheduled_posts(ctx: dict) -> int | None:
    from app.bot.factory import get_bot
    from app.services.content import publish_due_posts

    bot = get_bot()
    if bot is None:
        return None
    async with SessionFactory() as s:
        n = await publish_due_posts(s, bot)
        await s.commit()
    await _beat(ctx, "publish_scheduled_posts")
    return n


async def process_broadcasts(ctx: dict) -> int | None:
    from datetime import UTC, datetime

    from app.bot.factory import get_bot
    from app.services.content import materialize_broadcast, send_broadcast_batch

    bot = get_bot()
    if bot is None:
        return None
    sent = 0
    async with SessionFactory() as s:
        now = datetime.now(UTC)
        due = (
            await s.execute(
                select(Broadcast).where(
                    Broadcast.status == "scheduled", Broadcast.scheduled_at <= now
                )
            )
        ).scalars().all()
        for b in due:
            await materialize_broadcast(s, b)
            b.status = "sending"
            b.started_at = now
        sending = (
            await s.execute(select(Broadcast).where(Broadcast.status == "sending"))
        ).scalars().all()
        for b in sending:
            sent += await send_broadcast_batch(s, bot, b)
        await s.commit()
    await _beat(ctx, "process_broadcasts")
    return sent
