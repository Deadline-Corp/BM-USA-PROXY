"""Time-driven maintenance logic (called by worker cron jobs; unit-testable directly)."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log
from app.models import Access, AccessEvent, ChainCursor, Connection, Invoice, Order, Tariff
from app.services import ops_alerts, promos
from app.services import settings as settings_svc
from app.services.accesses import next_rotation_at
from app.services.notifications import enqueue
from app.services.provisioning import allocator
from app.services.provisioning.lifecycle import rotate_ip
from app.services.provisioning.registry import get_provisioner


def _utcnow() -> datetime:
    return datetime.now(UTC)


# How long before the end the last warning goes out. An hour was both too late to be
# useful on a monthly plan and impossible on the one-hour trial — a 60-minute access would
# have been warned the instant it was issued, so trials were excluded and got no warning
# at all. Ten minutes is short enough that every plan, trial included, can be told.
FINAL_WARNING = timedelta(minutes=10)


async def sweep_access_expiries(session: AsyncSession) -> dict[str, int]:
    """Warn at 24h and 10 min, expire+revoke when due. Idempotent via warned_* + dedupe."""
    now = _utcnow()
    # One lookup per plan per sweep, not per access — the sweep walks every live access
    # and they share a handful of plans between them.
    free_plans: dict[str, bool] = {}
    rows = (
        await session.execute(
            select(Access).where(Access.status.in_(("active", "expiring")))
        )
    ).scalars().all()
    warned = expired = 0
    for access in rows:
        if access.expires_at is None:
            continue
        if access.expires_at <= now:
            try:
                conn = await session.get(Connection, access.connection_id)
                if conn is not None and access.iproxy_access_id:
                    # All three resources, not just the http one: an expiry that left the
                    # socks5 access or the changeip link behind would hand the customer a
                    # proxy that outlives the period they paid for.
                    await get_provisioner().revoke(
                        iproxy_connection_id=conn.iproxy_connection_id,
                        iproxy_access_id=access.iproxy_access_id,
                        socks5_access_id=access.iproxy_socks5_access_id,
                        action_link_id=access.iproxy_action_link_id,
                    )
            except Exception as exc:  # noqa: BLE001 — best-effort revoke; log and continue
                log.warning("revoke.failed", access_id=access.id, error=str(exc))
            access.status = "expired"
            access.revoked_at = now
            session.add(AccessEvent(access_id=access.id, type="expired", actor="system"))
            await enqueue(
                session, user_id=access.user_id, template_code="access_expired",
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp:{access.id}",
            )
            expired += 1
        elif (
            access.expires_at <= now + FINAL_WARNING
            and access.warned_1h_at is None
        ):
            access.status = "expiring"
            access.warned_1h_at = now
            await enqueue(
                session, user_id=access.user_id,
                template_code=await _final_warning_template(session, access, free_plans),
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp10:{access.id}",
            )
            warned += 1
        else:
            # `warned_24h_at` keeps its name: it is a column, the rename would be a
            # migration, and what it records — "the advance warning has gone out" — has not
            # changed even though the lead time has.
            lead = advance_warning_lead(_granted_minutes(access))
            if (
                lead is not None
                # Never after the last call. Once the ten-minute warning has gone out this
                # branch becomes reachable on the next sweep, and it would tell somebody
                # with six minutes left that they have six hours. Latent before the lead
                # became a share of the plan; a Daily access reaches it every time now.
                and access.warned_1h_at is None
                and access.warned_24h_at is None
                and access.expires_at <= now + lead
            ):
                access.status = "expiring"
                access.warned_24h_at = now
                await enqueue(
                    session, user_id=access.user_id, template_code="access_expiring_soon",
                    payload={
                        "access_public_id": str(access.public_id),
                        "left": humanise_lead(lead),
                    },
                    dedupe_key=f"exp24:{access.id}",
                )
                warned += 1
    return {"warned": warned, "expired": expired}


_POOL_ALERT_STATE = "pool_low_alert_state"
POOL_CHECK_INTERVAL_SETTING = "pool_check_interval_minutes"
POOL_REPEAT_HOURS_SETTING = "pool_alert_repeat_hours"


async def check_pool_watermark(session: AsyncSession) -> dict[str, Any]:
    """Tell the operators when sellable stock drops below the configured floor.

    The `pool_low_watermark` setting has existed in the admin console since launch and
    nothing ever read it — measured on the client's account: seven connections against a
    threshold of ten, and no alert ever arrived, because this check did not exist. The
    setting looked like a working feature, which is worse than an absent one.

    "Free" is the allocator's own definition, so the number in the alert is the number of
    proxies that can actually be sold this second — not a count of phones that happen to
    be online. Stock reserved for unpaid invoices is therefore excluded, which means a
    burst of checkouts can trip this and it recovers when those invoices are paid or
    expire. That is the honest reading: during the burst there really is nothing to sell.

    State is kept so the alert fires on the way down rather than every pass, repeats only
    every few hours while stock stays low, and says so once when it recovers. A threshold
    of 0 (the default) disables the whole thing.

    Two cadences, both from the console, because they answer different questions:
    `pool_check_interval_minutes` is how often it looks — the delay before you hear about a
    drop at all — and `pool_alert_repeat_hours` is how often it says it again while stock
    stays low. Without the second, the same message would arrive on every check until
    somebody added phones, and an alert that repeats every few minutes is an alert people
    mute.

    The cron fires every minute and this returns early until the check interval has
    elapsed, rather than the interval living in the worker's schedule: a number typed in
    Settings then takes effect on the next minute instead of on the next deploy.
    """
    threshold = int(await settings_svc.get(session, "pool_low_watermark", 0) or 0)
    if threshold <= 0:
        return {"skipped": "disabled"}

    now = _utcnow()
    state = await settings_svc.get(session, _POOL_ALERT_STATE, {}) or {}
    interval = int(await settings_svc.get(session, POOL_CHECK_INTERVAL_SETTING, 5) or 5)
    repeat_hours = int(await settings_svc.get(session, POOL_REPEAT_HOURS_SETTING, 6) or 6)
    checked_at = state.get("checked_at")
    if interval > 1 and checked_at:
        with contextlib.suppress(ValueError, TypeError):
            if datetime.fromisoformat(str(checked_at)) + timedelta(minutes=interval) > now:
                return {"skipped": "not due"}

    free = await allocator.count_available(session)
    was_low = bool(state.get("low"))
    notified_at = state.get("notified_at")

    # One write at the end, whatever happened: `checked_at` has to move even on a pass that
    # sends nothing, or the interval above never elapses and the check runs every minute.
    new_state = {"low": was_low, "notified_at": notified_at, "checked_at": now.isoformat()}
    result: dict[str, Any] = {"free": free, "threshold": threshold, "alerted": False}

    if free < threshold:
        due = True
        if was_low and notified_at:
            with contextlib.suppress(ValueError, TypeError):
                due = datetime.fromisoformat(str(notified_at)) + timedelta(
                    hours=repeat_hours
                ) <= now
        new_state["low"] = True
        if due:
            await ops_alerts.notify_ops(
                session,
                f"⚠️ Pool is low: {free} proxies free, alert threshold is {threshold}.\n"
                "Add phones, or free some up in the iproxy console.",
            )
            new_state["notified_at"] = now.isoformat()
            result["alerted"] = True
    elif was_low:
        await ops_alerts.notify_ops(
            session, f"✅ Pool recovered: {free} proxies free (threshold {threshold})."
        )
        new_state = {"low": False, "notified_at": now.isoformat(), "checked_at": now.isoformat()}
        result["recovered"] = True

    await settings_svc.set_value(session, _POOL_ALERT_STATE, new_state)
    return result


async def sweep_auto_rotations(session: AsyncSession) -> dict[str, int]:
    """Rotate the IP of every live access whose auto-rotation interval has elapsed.

    Auto-rotation is ours, not iproxy's. iproxy has per-connection `ip_change_enabled` /
    `ip_change_interval_minutes` settings, but the Console API exposes no way to write
    them (PATCH/PUT on the connection and its settings both refuse), and they would be the
    wrong home anyway: they belong to the *phone*, so they would keep rotating after the
    access is revoked and follow the connection to the next buyer. Here the schedule
    belongs to the access that paid for it and dies with it.

    `last_rotation_at` is the clock, and lifecycle.rotate_ip stamps it however the rotation
    was triggered — so a buyer who rotates by hand resets their own interval instead of
    getting a second rotation moments later. `accesses.next_rotation_at` owns the reading
    of that clock, because the app screen has to wait for the same instant this acts on.
    """
    now = _utcnow()
    rows = (
        await session.execute(
            select(Access).where(
                Access.status.in_(("active", "expiring")),
                Access.auto_rotate_minutes.is_not(None),
            )
        )
    ).scalars().all()
    rotated = failed = 0
    for access in rows:
        # Shared with the payload the app reads, so the moment this sweep acts on is the
        # moment the screen is waiting for. Two copies of the rule would drift into a
        # screen that refreshes just before the change and shows the old address.
        due = next_rotation_at(access)
        if due is None or due > now:
            continue
        try:
            await rotate_ip(session, access=access, actor="auto")
            rotated += 1
        except Exception as exc:  # noqa: BLE001 — one bad phone must not stop the sweep
            # Stamped anyway so a connection that keeps failing is retried once per
            # interval instead of on every pass, a minute apart, forever.
            access.last_rotation_at = now
            failed += 1
            log.warning("auto_rotate.failed", access_id=access.id, error=str(exc))
    return {"rotated": rotated, "failed": failed}


def _granted_minutes(access: Access) -> float | None:
    """Total granted lifetime (issue → expiry) in minutes, or None if it can't be
    determined. starts_at + expires_at are stamped together at issue, so this is exact."""
    if access.starts_at is None or access.expires_at is None:
        return None
    return (access.expires_at - access.starts_at).total_seconds() / 60.0


async def _final_warning_template(
    session: AsyncSession, access: Access, cache: dict[str, bool]
) -> str:
    """Which wording the last warning uses — a free trial is told to buy a plan, a paid
    plan is told to renew.

    Decided on the plan's price rather than on the literal code "trial", so renaming that
    plan (or adding a second free one) cannot quietly start telling buyers to "buy a plan
    to extend" something they are already paying for.
    """
    code = access.tariff_code
    if code not in cache:
        price = await session.scalar(select(Tariff.price_usd).where(Tariff.code == code))
        cache[code] = price is not None and float(price) == 0
    return "trial_expiring_10m" if cache[code] else "access_expiring_10m"


# The furthest ahead anybody is warned. Beyond a day the message stops being useful — it
# arrives, gets forgotten, and the ten-minute one does the work anyway.
ADVANCE_WARNING_CAP = timedelta(hours=24)


def advance_warning_lead(granted_minutes: float | None) -> timedelta | None:
    """How long before the end to send the advance warning, or None for no advance warning.

    A quarter of what was bought, capped at a day.

    It used to be a flat 24 hours, sent only when the plan lasted longer than 24 hours —
    which meant a Daily buyer got no advance warning at all, only the ten-minute one, and
    that is exactly what the client reported on 2026-09-10. The flat rule had to exclude
    them, because a 24-hour warning on a 24-hour plan fires the moment it is issued.

    A share of the plan does not have that problem, and it says the same thing on every
    plan: you are three quarters of the way through. What the four live plans get:

        trial    1 hour   ->  15 min  -> suppressed, too close to the final warning
        daily    24 hours ->   6 hours
        weekly    7 days  ->  42 hours -> capped to 24
        monthly  30 days  -> 180 hours -> capped to 24

    So weekly and monthly are unchanged, daily gains six hours' notice, and a trial still
    gets the ten-minute call alone — two messages inside a quarter of an hour is not a
    warning, it is a repeat.
    """
    if granted_minutes is None:
        # Unknown length — an access issued before starts_at was stamped. A day's notice is
        # what every long plan gets and is the safe guess.
        return ADVANCE_WARNING_CAP
    lead = min(timedelta(minutes=granted_minutes / 4), ADVANCE_WARNING_CAP)
    return None if lead <= FINAL_WARNING * 2 else lead


def humanise_lead(lead: timedelta) -> str:
    """The lead time as the message says it: "24 hours", "6 hours", "45 min".

    In the payload rather than the template, because the template is one sentence for every
    plan and the number in it is different per plan. Hardcoding "24 hrs" is what made the
    message wrong the moment the lead stopped being 24 hours.
    """
    hours = lead.total_seconds() / 3600
    if hours >= 1:
        n = int(round(hours))
        return f"{n} hour" if n == 1 else f"{n} hours"
    return f"{int(round(lead.total_seconds() / 60))} min"


async def expire_invoices(session: AsyncSession) -> int:
    now = _utcnow()
    invoices = (
        await session.execute(
            select(Invoice).where(
                Invoice.status.in_(("created", "pending", "confirming")),
                Invoice.expires_at < now,
                # never expire an invoice whose on-chain deposit is already in flight —
                # the watcher's finalize pass only sees 'confirming' invoices, so
                # expiring one mid-confirmation strands the customer's funds.
                Invoice.matched_txid.is_(None),
            )
        )
    ).scalars().all()
    for inv in invoices:
        inv.status = "expired"
        order = await session.get(Order, inv.order_id)
        if order is not None and order.status == "awaiting_payment":
            order.status = "expired"
        # Whatever this order was holding goes back on the shelf now rather than when its
        # deadline lapses. The clock on the reservation is the safety net, not the plan:
        # waiting for it would keep phones out of the pool for the grace period after
        # every abandoned checkout.
        await allocator.release_reservations(session, order_id=inv.order_id)
        # Same reasoning as cancelling: an expired invoice sold nothing, so the promo code
        # it carried has not been used. Without this a one-use code is spent by a buyer who
        # opened the checkout and closed the app.
        await promos.release(session, order_id=inv.order_id)
    return len(invoices)


_WATCHER_ALERT_STATE = "onchain_watcher_alert_state"
# A chain whose cursor has not moved in this long is not slow, it is broken. Ticks run
# every fifteen seconds, so this is sixty missed passes — long enough that a provider
# hiccup or a redeploy never pages anybody.
WATCHER_STALL = timedelta(minutes=15)


async def check_watcher_liveness(session: AsyncSession) -> dict[str, Any]:
    """Tell the operators when a chain has stopped being scanned.

    Money arriving on a chain nobody is watching is the worst thing this system can do, and
    it is invisible from every screen: the customer sees "waiting for payment", the ledger
    stays empty, and the invoice quietly expires. It happened — Alchemy began refusing the
    Ethereum log scan, every tick errored, and the chain sat dead for nine hours while a
    customer's 6 USDT landed on our address unnoticed. Nothing anywhere said so.

    The cursor's own timestamp is the signal, because it is what every scan writes and what
    a failing scan therefore stops writing. Reading it needs no cooperation from the code
    that broke.

    Alerts once per chain per stall, and once more when it recovers, so a chain that stays
    broken does not turn into a message people learn to scroll past.
    """
    if settings.payment_provider != "onchain":
        return {"skipped": "provider not onchain"}

    from app.services.payments.onchain.config import get_onchain_config

    watched = set(get_onchain_config().chains_in_use())
    if not watched:
        return {"skipped": "no chains configured"}

    now = _utcnow()
    state = await settings_svc.get(session, _WATCHER_ALERT_STATE, {}) or {}
    rows = (await session.execute(select(ChainCursor))).scalars().all()
    seen = {c.chain: c.updated_at for c in rows}

    stalled: list[str] = []
    recovered: list[str] = []
    new_state = dict(state)
    for chain in sorted(watched):
        last = seen.get(chain)
        # No cursor at all is not a stall: the chain has simply never been scanned, which
        # is what a freshly configured rail looks like until its first tick.
        silent_for = now - last if last is not None else None
        is_stalled = silent_for is not None and silent_for > WATCHER_STALL
        was_stalled = bool(state.get(chain))
        if is_stalled and not was_stalled and silent_for is not None:
            stalled.append(f"{chain} (last scan {int(silent_for.total_seconds() // 60)} min ago)")
        elif was_stalled and not is_stalled:
            recovered.append(chain)
        new_state[chain] = is_stalled

    if stalled:
        with contextlib.suppress(Exception):
            await ops_alerts.notify_ops(
                session,
                "🚨 Payment watcher stopped: " + "; ".join(stalled) + ".\n"
                "Payments sent on these chains are NOT being credited. Check the worker log.",
            )
    if recovered:
        with contextlib.suppress(Exception):
            await ops_alerts.notify_ops(
                session, "✅ Payment watcher is scanning again: " + ", ".join(recovered) + "."
            )

    await settings_svc.set_value(session, _WATCHER_ALERT_STATE, new_state)
    return {"stalled": stalled, "recovered": recovered, "watched": len(watched)}
