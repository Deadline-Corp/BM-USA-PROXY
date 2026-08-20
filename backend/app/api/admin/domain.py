"""Admin domain API: dashboard, clients, tariffs, pool, accesses, orders, requests,
referrals, broadcasts, publications, faq, notifications, system settings.

Broadcast-send and post-publish flip status here; the worker crons (publish_scheduled_posts,
process_broadcasts) do the real Telegram dispatch via app.services.content. iproxy sync runs
in the worker too (real-provider mode). Everything else is wired against the real tables.
"""

from __future__ import annotations

import re
import secrets
import typing
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, File, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    ColumnElement,
    Select,
    String,
    and_,
    cast,
    distinct,
    false,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# A model attribute (`User.email`) is an InstrumentedAttribute, not a ColumnElement, even
# though both answer .ilike(). ColumnOperators is the common ancestor that actually
# declares ilike, so it is the honest type for "something this can search on"; select()
# and .where() want their own broader aliases, which is why the two helpers below are
# annotated differently rather than sharing one type.
from sqlalchemy.sql._typing import _ColumnExpressionArgument, _ColumnsClauseArgument
from sqlalchemy.sql.operators import ColumnOperators

from app.api.deps import CurrentAdmin, DbSession
from app.core.errors import Conflict, NotFound, ValidationError
from app.core.security import hash_password
from app.models import (
    AccessEvent,
    AdminUser,
    AppSetting,
    AuditLog,
    Broadcast,
    Channel,
    Connection,
    ConversationMessage,
    FaqItem,
    Invoice,
    Location,
    NotificationOutbox,
    OnchainDepositLedger,
    Order,
    PaymentEvent,
    Payout,
    Post,
    ReferralLedger,
    Refund,
    Request,
    RequestComment,
    StateCity,
    Tariff,
    TosAcceptance,
    User,
)
from app.models.access import Access
from app.services import admin_telegram, audit, content, media, referral
from app.services import settings as settings_svc
from app.services.notifications import enqueue
from app.services.provisioning import allocator
from app.services.provisioning.lifecycle import (
    extend_access,
    provision_access,
    revoke_access,
    swap_access,
)
from app.services.provisioning.state_from_name import US_STATE_CODES, state_from_name

router = APIRouter(prefix="/api/admin", tags=["admin"])

_ACTIVE_ACCESS = ("provisioning", "active", "expiring")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)


def _search_terms(q: str) -> list[str]:
    """Split a search box into the words a row has to contain, each reduced to a stem.

    The console shows these rows in English — "Revoked", "Banned", "App setting" — while
    the columns hold `access.revoke`, `client.ban`, `app_setting`. Someone typing what
    they can see has to find the row, so a regular past-tense ending comes off before
    matching, and a consonant doubled to carry it ("banned" → "bann" → "ban") comes off
    with it. Matching is by substring, so an over-short stem still hits: "revok" finds
    `access.revoke`.

    Only plain short words are stemmed. A hash, an address or a handle is matched exactly
    as typed — chopping two characters off a transaction id to guess at grammar would be
    absurd.
    """
    # Split on punctuation and spaces, keep letters — any letters. The old pattern listed
    # A-Za-z and therefore treated every Cyrillic character as a separator: "сл" tokenised
    # to nothing at all, and a query of nothing filters nothing, so typing it returned the
    # entire table. The same silence hid a real gap — Telegram first names are frequently
    # Cyrillic, and searching one never worked. "#" stays a separator on purpose: somebody
    # pasting "#45" means order 45.
    words = [w for w in re.split(r"[^\w@.-]+", q.strip().lower(), flags=re.UNICODE) if w]
    terms: list[str] = []
    for word in words:
        # Stemming is English grammar, so it is only applied to words made of ASCII
        # letters. "-ed" means nothing to a Russian name and chopping it would corrupt one.
        if word.isascii() and word.isalpha() and len(word) <= 12:
            # Only "-ed". A bare trailing "d" would eat the last letter of names — "fred"
            # became "fre", which then matched every row with "free" or "frequency" in it.
            # Nothing needs it: "approved" and "revoked" both end in "ed" already.
            if len(word) > 4 and word.endswith("ed"):
                word = word[:-2]
            if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiou":
                word = word[:-1]
        terms.append(word)
    return terms


def _sub(
    column: _ColumnsClauseArgument[Any], where: _ColumnExpressionArgument[bool]
) -> ColumnElement[Any]:
    """One column of a related row, usable as a search column on the row being listed.

    A correlated scalar subquery rather than a join: the search on some of these screens
    reaches three tables, and joining all of them into both the page query and its COUNT
    restates the schema in every endpoint. A NULL from a missing related row simply never
    matches, which is the behaviour we want anyway.
    """
    return select(column).where(where).scalar_subquery()


def _search_condition(
    q: str | None,
    columns: Sequence[ColumnOperators],
    *,
    number_columns: Sequence[ColumnOperators] = (),
    opaque_columns: Sequence[ColumnOperators] = (),
) -> ColumnElement[bool] | None:
    """Every word of the query somewhere in the row; each word may land in any column.

    One box over every column beats one box per column: the operator holds a value —
    a handle, a city, a status — and usually cannot say which column it belongs to. AND
    across words is what makes a second word narrow rather than widen, which is the whole
    reason for typing it.

    Three kinds of column, because they answer to different questions:

    * `columns` — text. Substring, always. Half a handle or half a city is how people
      search, and "nnic" has to find @NNick777.
    * `number_columns` — counters. Equality, always: LIKE on them buries order 12 under
      120 and 512, and "1" matches the lot. Equality is *added to* the text search, not
      substituted for it, so nothing a screen used to find stops being findable.
    * `opaque_columns` — UUIDs, wallet addresses, transaction hashes. Substring, but only
      for a term that is not all digits. They are pasted whole and they contain digits
      everywhere, so against "45" they match nearly every row and drown the real answer.

    A term of digits therefore searches the counters *and* the text — 777 finds @NNick777,
    0000 finds the account whose telegram id contains it, 12 finds order 12 without
    dragging in 120 — while leaving the hashes and UUIDs alone.
    """
    if not q or not q.strip():
        return None
    terms = _search_terms(q)
    if not terms:
        # Somebody typed something — punctuation, an emoji, a stray keystroke — and it
        # reduced to no searchable word. Returning None here means "no filter", which
        # answers a search that found nothing with every row in the table. Nothing found
        # has to look like nothing found.
        return false()

    def matches(term: str) -> list[ColumnElement[bool]]:
        # `.ilike()` is declared on ColumnOperators as returning ColumnOperators, while at
        # runtime it is the boolean BinaryExpression `or_` needs. The stub is looser than
        # the reality, so the narrowing happens once, here, rather than at every call site.
        digits = term.isdigit()
        found = [typing.cast("ColumnElement[bool]", col.ilike(f"%{term}%")) for col in columns]
        if not digits:
            found += [
                typing.cast("ColumnElement[bool]", col.ilike(f"%{term}%"))
                for col in opaque_columns
            ]
        if digits:
            found += [
                typing.cast("ColumnElement[bool]", col == int(term)) for col in number_columns
            ]
        return found

    return and_(*[or_(*matches(term)) for term in terms])


async def _paginated(
    session: AsyncSession, stmt: Any, count_stmt: Any, *, limit: int, offset: int
) -> tuple[list[Any], int]:
    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
    return list(rows), total


# ── user display helper (shared by Client/Access/Order/Request/Payout/etc. views) ──
def _user_display(user: User | None) -> str:
    """Mirrors the admin frontend's expected `user` label: @handle > first name > #id."""
    if user is None:
        return "—"
    if user.tg_username:
        return f"@{user.tg_username}"
    if user.first_name:
        return user.first_name
    return f"#{user.id}"


async def _user_display_map(session: DbSession, user_ids: Sequence[int | None]) -> dict[int | None, str]:
    """Bulk-resolve `_user_display` for many ids at once (avoids N+1 in list endpoints)."""
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(User.id, User.tg_username, User.first_name).where(User.id.in_(ids))
        )
    ).all()
    result: dict[int | None, str] = {}
    for uid, tg_username, first_name in rows:
        if tg_username:
            result[uid] = f"@{tg_username}"
        elif first_name:
            result[uid] = first_name
        else:
            result[uid] = f"#{uid}"
    return result


async def _referral_code_map(
    session: DbSession, user_ids: Sequence[int | None]
) -> dict[int | None, str]:
    """Bulk-resolve referral codes, same shape and reason as `_user_display_map`."""
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    rows = (
        await session.execute(select(User.id, User.referral_code).where(User.id.in_(ids)))
    ).all()
    return dict(rows)  # type: ignore[arg-type]


async def _admin_display_map(
    session: DbSession, admin_ids: Sequence[int | None]
) -> dict[int | None, str]:
    """Bulk-resolve admin display labels (display_name, falling back to email)."""
    ids = {aid for aid in admin_ids if aid is not None}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(AdminUser.id, AdminUser.display_name, AdminUser.email).where(
                AdminUser.id.in_(ids)
            )
        )
    ).all()
    return {aid: (display_name or email) for aid, display_name, email in rows}


# ── no role tiers ────────────────────────────────────────────────────────
# Every signed-in admin can do everything. There used to be an owner tier gating
# settings, terms, admin accounts and the two order-money actions, plus a USD ceiling on
# what an operator could refund without one.
#
# It went because the split described a company that does not exist here: the same two
# people run the business and own it, so "ask an owner" meant "ask the person sitting
# next to you, who has the same password manager". A gate nobody is on the other side of
# does not protect anything — it just makes the console refuse work at the moment someone
# is trying to do it. What actually limits damage stays: every action is audit-logged
# with who did it, and the on-chain rails hold no keys the backend could spend.
#
# The `role` column is still on admin_users, unused, so this is reversible without a
# migration if the client ever wants tiers back.


# ── dashboard ────────────────────────────────────────────────────────────
@router.get("/dashboard")
async def dashboard(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    now = _utcnow()

    async def _revenue_since(since: datetime) -> float:
        val = await session.scalar(
            select(func.coalesce(func.sum(Order.amount_usd), 0)).where(
                Order.status == "completed", Order.paid_at >= since
            )
        )
        return float(val or 0)

    revenue_today = await _revenue_since(now.replace(hour=0, minute=0, second=0, microsecond=0))
    revenue_7d = await _revenue_since(now - timedelta(days=7))
    revenue_30d = await _revenue_since(now - timedelta(days=30))

    active_accesses = int(
        await session.scalar(
            select(func.count()).select_from(Access).where(Access.status.in_(_ACTIVE_ACCESS))
        )
        or 0
    )
    free_pool = await allocator.count_available(session, location_id=None, carrier=None)
    pending_manual_review = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.status == "manual_review")
        )
        or 0
    )
    new_requests = int(
        await session.scalar(
            select(func.count()).select_from(Request).where(Request.status == "new")
        )
        or 0
    )
    unread_messages = int(
        await session.scalar(
            select(func.count())
            .select_from(ConversationMessage)
            .where(ConversationMessage.direction == "in", ConversationMessage.read_at.is_(None))
        )
        or 0
    )
    return {
        "revenue": {"today": revenue_today, "d7": revenue_7d, "d30": revenue_30d},
        "active_accesses": active_accesses,
        "free_pool": free_pool,
        "pending_manual_review": pending_manual_review,
        "new_requests": new_requests,
        "unread_messages": unread_messages,
    }


@router.get("/dashboard/revenue")
async def dashboard_revenue(
    admin: CurrentAdmin, session: DbSession, days: int = 30
) -> list[dict[str, Any]]:
    days = max(1, min(days, 365))
    rows = await session.execute(
        text(
            """
            SELECT date(paid_at) AS d, coalesce(sum(amount_usd), 0) AS revenue
            FROM orders
            WHERE status = 'completed' AND paid_at >= now() - make_interval(days => :days)
            GROUP BY date(paid_at)
            ORDER BY d
            """
        ),
        {"days": days},
    )
    return [{"date": r[0].isoformat(), "revenue": float(r[1])} for r in rows]


# ── clients ──────────────────────────────────────────────────────────────
@router.get("/clients")
async def list_clients(
    admin: CurrentAdmin,
    session: DbSession,
    q: str | None = None,
    has_active: bool | None = None,
    banned: bool | None = None,
    since: str | None = None,
    before: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if since:
        stmt = stmt.where(User.created_at >= _parse_day(since))
        count_stmt = count_stmt.where(User.created_at >= _parse_day(since))
    if before:
        end = _parse_day(before) + timedelta(days=1)
        stmt = stmt.where(User.created_at < end)
        count_stmt = count_stmt.where(User.created_at < end)
    # The telegram id is cast rather than compared as a number, so a partial one matches
    # like every other column — an operator reading an id off a screenshot types the part
    # they can see.
    cond = _search_condition(
        q,
        [
            User.tg_username,
            User.first_name,
            User.last_name,
            User.email,
            User.referral_code,
            cast(User.tg_user_id, String),
        ],
        number_columns=[User.tg_user_id],
    )
    if cond is not None:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if banned is not None:
        status_val = "banned" if banned else "active"
        stmt = stmt.where(User.status == status_val)
        count_stmt = count_stmt.where(User.status == status_val)
    if has_active is not None:
        active_sub = select(Access.user_id).where(Access.status.in_(_ACTIVE_ACCESS)).distinct()
        if has_active:
            stmt = stmt.where(User.id.in_(active_sub))
            count_stmt = count_stmt.where(User.id.in_(active_sub))
        else:
            stmt = stmt.where(User.id.not_in(active_sub))
            count_stmt = count_stmt.where(User.id.not_in(active_sub))
    stmt = stmt.order_by(User.created_at.desc())

    rows, total = await _paginated(session, stmt, count_stmt, limit=limit, offset=offset)
    user_ids = [user.id for (user,) in rows]
    # Bulk queries replace the per-client N+1 (total_spent + active_count + unread +
    # terms-accepted). Kept separate to avoid a cartesian-product inflation between
    # orders/accesses/messages/tos_acceptances.
    spent_by_user: dict[int, float] = {}
    active_by_user: dict[int, int] = {}
    unread_by_user: dict[int, int] = {}
    tos_accepted_by_user: dict[int, str] = {}
    tos_version = None
    if user_ids:
        spent_rows = (
            await session.execute(
                select(User.id, func.coalesce(func.sum(Order.amount_usd), 0))
                .outerjoin(Order, (Order.user_id == User.id) & (Order.status == "completed"))
                .where(User.id.in_(user_ids))
                .group_by(User.id)
            )
        ).all()
        for uid, spent in spent_rows:
            spent_by_user[uid] = float(spent or 0)
        active_rows = (
            await session.execute(
                select(User.id, func.count(Access.id))
                .outerjoin(Access, (Access.user_id == User.id) & (Access.status.in_(_ACTIVE_ACCESS)))
                .where(User.id.in_(user_ids))
                .group_by(User.id)
            )
        ).all()
        for uid, active in active_rows:
            active_by_user[uid] = int(active or 0)
        # Same "unread inbound, not yet read" definition as the sidebar badge
        # (dashboard_summary above) and the same read_at the dossier stamps on open —
        # one GROUP BY for the whole page rather than a query per row.
        unread_rows = (
            await session.execute(
                select(ConversationMessage.user_id, func.count(ConversationMessage.id))
                .where(
                    ConversationMessage.user_id.in_(user_ids),
                    ConversationMessage.direction == "in",
                    ConversationMessage.read_at.is_(None),
                )
                .group_by(ConversationMessage.user_id)
            )
        ).all()
        for uid, cnt in unread_rows:
            unread_by_user[uid] = int(cnt or 0)
        # Same semantics as services.users.is_tos_accepted: accepted means a row on file
        # for the *currently published* version, not merely "accepted some version once".
        tos_version = (await settings_svc.get(session, "tos", {})).get("version")
        if tos_version:
            tos_rows = (
                await session.execute(
                    select(TosAcceptance.user_id, TosAcceptance.accepted_at).where(
                        TosAcceptance.user_id.in_(user_ids),
                        TosAcceptance.version == tos_version,
                    )
                )
            ).all()
            for uid, accepted_at in tos_rows:
                tos_accepted_by_user[uid] = accepted_at.isoformat()
    items = []
    for (user,) in rows:
        items.append(
            {
                "id": str(user.id),
                "telegram_username": user.tg_username,
                "telegram_id": str(user.tg_user_id),
                "display_name": user.first_name,
                "created_at": user.created_at.isoformat(),
                "has_active_access": active_by_user.get(user.id, 0) > 0,
                "banned": user.status == "banned",
                "operator_note": user.operator_note,
                "unread_messages": unread_by_user.get(user.id, 0),
                # No version published yet (tos_version falsy) gates nobody — same
                # vacuous-true fallback as is_tos_accepted.
                "terms_accepted": not tos_version or user.id in tos_accepted_by_user,
                "terms_accepted_at": tos_accepted_by_user.get(user.id),
            }
        )
    return {"items": items, "total": total}


async def _get_user(session: DbSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("client not found")
    return user


@router.get("/clients/{client_id}")
async def client_dossier(client_id: int, admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    user = await _get_user(session, client_id)

    tos_row = await session.scalar(
        select(TosAcceptance)
        .where(TosAcceptance.user_id == user.id)
        .order_by(TosAcceptance.version.desc())
        .limit(1)
    )
    accesses = (
        (await session.execute(
            select(Access).where(Access.user_id == user.id).order_by(Access.created_at.desc())
        )).scalars().all()
    )
    orders = (
        (await session.execute(
            select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
        )).scalars().all()
    )
    requests = (
        (await session.execute(
            select(Request).where(Request.user_id == user.id).order_by(Request.created_at.desc())
        )).scalars().all()
    )
    referred_count = int(
        await session.scalar(
            select(func.count()).select_from(User).where(User.referrer_user_id == user.id)
        )
        or 0
    )
    referral_balances = await referral.balances(session, user.id)

    # bulk-resolve city/carrier per access (via its connection's location)
    conn_ids = {a.connection_id for a in accesses}
    conn_lookup: dict[int, tuple[str | None, str | None, str | None]] = {}
    if conn_ids:
        conn_rows = (
            await session.execute(
                select(
                    Connection.id,
                    Location.city,
                    Connection.carrier,
                    Connection.iproxy_connection_id,
                )
                .outerjoin(Location, Location.id == Connection.location_id)
                .where(Connection.id.in_(conn_ids))
            )
        ).all()
        for cid, city, carrier, iproxy_id in conn_rows:
            conn_lookup[cid] = (city, carrier, iproxy_id)

    # bulk-resolve provider per order (via its most recent invoice)
    order_ids = [o.id for o in orders]
    provider_by_order: dict[int, str] = {}
    if order_ids:
        inv_rows = (
            await session.execute(
                select(Invoice.order_id, Invoice.provider)
                .where(Invoice.order_id.in_(order_ids))
                .order_by(Invoice.created_at.desc())
            )
        ).all()
        for oid, provider in inv_rows:
            provider_by_order.setdefault(oid, provider)

    # conversation thread (inbound client DMs + operator replies); viewing the dossier
    # marks the client's unread inbound messages as read (drives the operator badge).
    msgs = (
        await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.user_id == user.id)
            .order_by(ConversationMessage.created_at.asc())
            .limit(200)
        )
    ).scalars().all()
    now = _utcnow()
    for m in msgs:
        if m.direction == "in" and m.read_at is None:
            m.read_at = now
    admin_display = await _admin_display_map(session, [m.admin_id for m in msgs])

    return {
        "profile": {
            "id": str(user.id),
            "telegram_username": user.tg_username,
            "telegram_id": str(user.tg_user_id),
            "display_name": user.first_name,
            "created_at": user.created_at.isoformat(),
            "has_active_access": any(a.status in _ACTIVE_ACCESS for a in accesses),
            "banned": user.status == "banned",
            "operator_note": user.operator_note,
        },
        "tos": {
            "accepted": tos_row is not None,
            "version": tos_row.version if tos_row else None,
            "accepted_at": tos_row.accepted_at.isoformat() if tos_row else None,
            "answers": tos_row.answers if tos_row else {},
        },
        "accesses": [
            {
                "id": str(a.public_id),
                "tariff_code": a.tariff_code,
                "status": a.status,
                "city": conn_lookup.get(a.connection_id, (None, None, None))[0],
                "carrier": conn_lookup.get(a.connection_id, (None, None, None))[1],
                "ip": None,
                # Which phone is serving it — support's next stop is that connection in
                # the iproxy console.
                "connection_id": conn_lookup.get(a.connection_id, (None, None, None))[2],
                # The dossier is where "why did this customer lose their proxy" gets asked,
                # so the reason an operator typed on revoke belongs here too.
                "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
                "revoke_reason": a.revoke_reason,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in accesses
        ],
        "orders": [
            {
                "id": str(o.public_id),
                "number": o.id,
                "status": o.status,
                "provider": provider_by_order.get(o.id),
                "amount_usd": float(o.amount_usd),
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ],
        "referral": {
            "code": user.referral_code,
            # Arrivals at the bot through this person's link. Beside `attached` it says
            # whether their link is being opened and going nowhere, which is the difference
            # between a referrer who needs a bigger audience and one who needs a better pitch.
            "link_opens": int(user.referral_clicks or 0),
            "attached": referred_count,
            "balance_usd": referral_balances["available"],
        },
        "requests": [
            {
                "id": str(r.id),
                "status": r.status,
                "subject": r.subject,
                "created_at": r.created_at.isoformat(),
            }
            for r in requests
        ],
        "messages": [
            {
                "id": str(m.id),
                "direction": m.direction,
                "text": m.body,
                "admin": admin_display.get(m.admin_id) if m.admin_id else None,
                # Outbound rows have three authors now — an operator, the canned
                # acknowledgement, and the assistant. Without this the dossier shows the
                # last two identically, and nobody can tell what the client was actually told.
                "via_ai": bool(m.via_ai),
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


class ClientPatch(BaseModel):
    operator_note: str


@router.patch("/clients/{client_id}")
async def patch_client(
    client_id: int, body: ClientPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    user = await _get_user(session, client_id)
    user.operator_note = body.operator_note
    await audit.write(session, admin_id=admin.id, action="client.update", entity="user",
                       entity_id=user.id)
    return {"id": user.id, "operator_note": user.operator_note}


@router.post("/clients/{client_id}/ban")
async def ban_client(client_id: int, admin: CurrentAdmin, session: DbSession) -> dict[str, str]:
    user = await _get_user(session, client_id)
    # Revoke any live access first — a ban must also kill the proxy the client holds,
    # otherwise the deleted-from-the-app user keeps routing traffic through iproxy.
    live = (
        await session.execute(
            select(Access).where(Access.user_id == user.id, Access.status.in_(_ACTIVE_ACCESS))
        )
    ).scalars().all()
    for access in live:
        await revoke_access(
            session, access=access, reason="account banned", actor=f"admin:{admin.id}"
        )
    user.status = "banned"
    await audit.write(session, admin_id=admin.id, action="client.ban", entity="user",
                       entity_id=user.id, after={"revoked_accesses": len(live)})
    return {"status": user.status}


@router.post("/clients/{client_id}/unban")
async def unban_client(client_id: int, admin: CurrentAdmin, session: DbSession) -> dict[str, str]:
    user = await _get_user(session, client_id)
    user.status = "active"
    await audit.write(session, admin_id=admin.id, action="client.unban", entity="user",
                       entity_id=user.id)
    return {"status": user.status}


class ClientMessage(BaseModel):
    text: str = Field(max_length=4096)


@router.post("/clients/{client_id}/message")
async def message_client(
    client_id: int, body: ClientMessage, admin: CurrentAdmin, session: DbSession
) -> dict[str, bool]:
    user = await _get_user(session, client_id)
    # Record the outbound side of the thread so the dossier shows the full conversation.
    session.add(
        ConversationMessage(
            user_id=user.id, direction="out", admin_id=admin.id, body=body.text
        )
    )
    await enqueue(
        session, user_id=user.id, template_code="operator_message", payload={"text": body.text}
    )
    await audit.write(session, admin_id=admin.id, action="client.message", entity="user",
                       entity_id=user.id)
    return {"queued": True}


# ── cities (state → the city it is sold as) ─────────────────────────────
class StateCityBody(BaseModel):
    state_code: str = Field(min_length=2, max_length=2)
    city: str = Field(min_length=1, max_length=80)


def _normalise_state(code: str) -> str:
    code = code.strip().upper()
    if code not in US_STATE_CODES:
        raise ValidationError(f"'{code}' is not a US state code")
    return code


@router.get("/cities")
async def list_state_cities(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    """The client's state→city mapping, plus what the pool is asking for.

    `unmapped` is the useful half: states written into connection names that have no city
    yet. Without it the screen is a list to maintain in the dark — a phone named `att113_MI`
    would quietly keep its exit-IP city and nobody would know a row was missing.
    """
    rows = (
        await session.execute(
            select(StateCity.state_code, StateCity.city, StateCity.updated_at).order_by(
                StateCity.state_code
            )
        )
    ).all()
    mapped = {code for code, _city, _ts in rows}

    # Count phones per state as named, so an operator can see how much each row covers and
    # which missing row matters most.
    per_state: dict[str, int] = {}
    for (name,) in (await session.execute(select(Connection.name))).all():
        code = state_from_name(name)
        if code:
            per_state[code] = per_state.get(code, 0) + 1

    return {
        "items": [
            {
                "state_code": code,
                "city": city,
                "connections": per_state.get(code, 0),
                "updated_at": ts.isoformat() if ts else None,
            }
            for code, city, ts in rows
        ],
        "unmapped": [
            {"state_code": code, "connections": count}
            for code, count in sorted(per_state.items(), key=lambda kv: -kv[1])
            if code not in mapped
        ],
    }


@router.put("/cities/{state_code}")
async def upsert_state_city(
    state_code: str, body: StateCityBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Create or repoint one state. PUT because the state is the key — saving twice is the
    same as saving once, and there is no way to end up with two cities for one state."""
    code = _normalise_state(state_code)
    if _normalise_state(body.state_code) != code:
        raise ValidationError("state code in the URL and the body disagree")
    city = body.city.strip()
    await session.execute(
        pg_insert(StateCity)
        .values(state_code=code, city=city, updated_by=admin.id)
        .on_conflict_do_update(
            index_elements=["state_code"],
            set_={"city": city, "updated_by": admin.id, "updated_at": func.now()},
        )
    )
    await audit.write(session, admin_id=admin.id, action="state_city.save", entity="state_city",
                       entity_id=code, after={"city": city})
    return {"state_code": code, "city": city}


@router.delete("/cities/{state_code}")
async def delete_state_city(
    state_code: str, admin: CurrentAdmin, session: DbSession
) -> dict[str, bool]:
    """Removing a row does not orphan anything: phones named for that state fall back to
    the city their exit IP resolves to, which is what happened before any of this existed."""
    code = _normalise_state(state_code)
    row = await session.get(StateCity, code)
    if row is None:
        raise NotFound("no city mapped for this state")
    await session.delete(row)
    await audit.write(session, admin_id=admin.id, action="state_city.delete",
                       entity="state_city", entity_id=code, before={"city": row.city})
    return {"deleted": True}


@router.get("/locations")
async def list_locations(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    """What can be issued right now: cities with something free, and on which carriers.

    Read-only on purpose. The Locations *editor* was removed — cities are derived from
    what iproxy reports and there was nothing for an operator to decide there — but a
    dropdown still needs the ids, and issuing an access is where "which city" is a real
    choice.

    It lists availability rather than inventory. Listing every city the pool has ever seen
    meant an operator could pick one whose phones are all sold or offline, and find that
    out only from a failed issue. What is offered here is exactly what the allocator would
    accept — see allocator.available_locations for the shared definition of free.
    """
    return await allocator.available_locations(session)


class IssueAccessBody(BaseModel):
    tariff_code: str
    connection_id: int | None = None
    location_id: int | None = None
    carrier: str | None = None


@router.post("/clients/{client_id}/issue-access")
async def issue_access(
    client_id: int, body: IssueAccessBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    user = await _get_user(session, client_id)
    tariff = await session.scalar(select(Tariff).where(Tariff.code == body.tariff_code))
    if tariff is None:
        raise NotFound("tariff not found")

    now = _utcnow()
    order = Order(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_code=tariff.code,
        duration_minutes=tariff.duration_minutes,
        amount_usd=tariff.price_usd,
        location_id=body.location_id,
        carrier=body.carrier,
        status="paid",
        origin="admin",
        paid_at=now,
    )
    session.add(order)
    await session.flush()

    access = await provision_access(session, order=order)
    await audit.write(
        session, admin_id=admin.id, action="client.issue_access", entity="access",
        entity_id=access.id, after={"order_id": order.id, "tariff_code": tariff.code},
    )
    return {
        "order": {"public_id": str(order.public_id), "status": order.status},
        "access": {"public_id": str(access.public_id), "status": access.status},
    }


# ── tariffs ──────────────────────────────────────────────────────────────
def _tariff_view(t: Tariff) -> dict[str, Any]:
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "description": t.description,
        "kind": t.kind,
        "duration_minutes": t.duration_minutes,
        "price_usd": float(t.price_usd),
        "max_per_user": t.max_per_user,
        "max_user_swaps": t.max_user_swaps,
        "auto_issue": t.auto_issue,
        "is_active": t.is_active,
        "sort_order": t.sort_order,
    }


@router.get("/tariffs")
async def list_tariffs(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Tariff).order_by(Tariff.sort_order))).scalars().all()
    return [_tariff_view(t) for t in rows]


class TariffBody(BaseModel):
    code: str
    name: str
    description: str = ""
    kind: str = "auto"
    duration_minutes: int | None = None
    price_usd: float = 0
    max_per_user: int | None = None
    max_user_swaps: int = 0
    auto_issue: bool = True
    is_active: bool = True
    sort_order: int = 100


@router.post("/tariffs", status_code=201)
async def create_tariff(
    body: TariffBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    existing = await session.scalar(select(Tariff.id).where(Tariff.code == body.code))
    if existing is not None:
        raise Conflict("tariff code already exists")
    tariff = Tariff(**body.model_dump())
    session.add(tariff)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="tariff.create", entity="tariff",
                       entity_id=tariff.id, after=body.model_dump())
    return _tariff_view(tariff)


async def _get_tariff(session: DbSession, tariff_id: int) -> Tariff:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None:
        raise NotFound("tariff not found")
    return tariff


class TariffPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    kind: str | None = None
    duration_minutes: int | None = None
    price_usd: float | None = None
    max_per_user: int | None = None
    max_user_swaps: int | None = None
    auto_issue: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.patch("/tariffs/{tariff_id}")
async def patch_tariff(
    tariff_id: int, body: TariffPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    tariff = await _get_tariff(session, tariff_id)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tariff, field, value)
    await audit.write(session, admin_id=admin.id, action="tariff.update", entity="tariff",
                       entity_id=tariff.id, after=updates)
    return _tariff_view(tariff)


@router.post("/tariffs/{tariff_id}/toggle")
async def toggle_tariff(
    tariff_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    tariff = await _get_tariff(session, tariff_id)
    tariff.is_active = not tariff.is_active
    await audit.write(session, admin_id=admin.id, action="tariff.toggle", entity="tariff",
                       entity_id=tariff.id, after={"is_active": tariff.is_active})
    return _tariff_view(tariff)


# ── connections / pool ──────────────────────────────────────────────────
def _connection_view(
    c: Connection, *, city: str | None, state: str | None, slots_used: int
) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "external_id": c.iproxy_connection_id,
        "city": city,
        "state": state,
        "carrier": c.carrier,
        "online": c.online_status == "online",
        "is_sellable": c.is_sellable,
        "tier": c.tier,
        "location_id": str(c.location_id) if c.location_id is not None else None,
        "health_note": c.health_note,
        "slots_total": 1,
        "slots_used": slots_used,
        # Held from the iproxy side rather than by anything we sold. The card says so
        # explicitly, because otherwise this phone reads as free here while it is serving
        # somebody's traffic — the exact mismatch the client saw on the demo.
        "external_holds": c.external_access_count,
        "external_checked_at": (
            c.external_checked_at.isoformat() if c.external_checked_at else None
        ),
        "last_rotated_at": c.last_rotated_at.isoformat() if c.last_rotated_at else None,
    }


async def _connection_slots_used(session: DbSession, connection_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Access)
            .where(Access.connection_id == connection_id, Access.status.in_(_ACTIVE_ACCESS))
        )
        or 0
    )


@router.get("/connections")
async def list_connections(
    admin: CurrentAdmin,
    session: DbSession,
    city: str | None = None,
    carrier: str | None = None,
    online: bool | None = None,
    sellable: bool | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """The phone pool. ``q`` searches everything printed on a device card.

    No date range here, unlike the other lists: a card shows no date, so a from/to filter
    would be a control with nothing on screen to check it against.
    """
    stmt = select(Connection)
    count_stmt = select(func.count()).select_from(Connection)
    search = _search_condition(
        q,
        [
            Connection.iproxy_connection_id,
            Connection.name,
            Connection.carrier,
            Connection.tier,
            Connection.online_status,
            Connection.health_note,
            _sub(Location.city, Location.id == Connection.location_id),
            _sub(Location.state_code, Location.id == Connection.location_id),
        ],
    )
    if search is not None:
        stmt = stmt.where(search)
        count_stmt = count_stmt.where(search)
    if city:
        loc_ids = select(Location.id).where(Location.city.ilike(f"%{city}%"))
        stmt = stmt.where(Connection.location_id.in_(loc_ids))
        count_stmt = count_stmt.where(Connection.location_id.in_(loc_ids))
    if carrier:
        stmt = stmt.where(Connection.carrier == carrier)
        count_stmt = count_stmt.where(Connection.carrier == carrier)
    if online is not None:
        status_val = "online" if online else "offline"
        stmt = stmt.where(Connection.online_status == status_val)
        count_stmt = count_stmt.where(Connection.online_status == status_val)
    if sellable is not None:
        stmt = stmt.where(Connection.is_sellable == sellable)
        count_stmt = count_stmt.where(Connection.is_sellable == sellable)
    stmt = stmt.order_by(Connection.id)

    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    # bulk-resolve city/state (via Location) + slots_used (active-access count) per connection
    location_ids = {c.location_id for c in rows if c.location_id is not None}
    location_lookup: dict[int | None, tuple[str | None, str | None]] = {}
    if location_ids:
        loc_rows = (
            await session.execute(
                select(Location.id, Location.city, Location.state_code).where(
                    Location.id.in_(location_ids)
                )
            )
        ).all()
        for lid, city_val, state_val in loc_rows:
            location_lookup[lid] = (city_val, state_val)

    connection_ids = [c.id for c in rows]
    slots_used_by_conn: dict[int, int] = {}
    if connection_ids:
        used_rows = (
            await session.execute(
                select(Access.connection_id, func.count())
                .where(
                    Access.connection_id.in_(connection_ids),
                    Access.status.in_(_ACTIVE_ACCESS),
                )
                .group_by(Access.connection_id)
            )
        ).all()
        slots_used_by_conn = {cid: int(count) for cid, count in used_rows}

    items = [
        _connection_view(
            c,
            city=location_lookup.get(c.location_id, (None, None))[0],
            state=location_lookup.get(c.location_id, (None, None))[1],
            slots_used=slots_used_by_conn.get(c.id, 0),
        )
        for c in rows
    ]
    return {"items": items, "total": total}


class ConnectionPatch(BaseModel):
    is_sellable: bool | None = None
    tier: str | None = None
    location_id: int | None = None
    carrier: str | None = None
    health_note: str | None = None


@router.patch("/connections/{connection_id}")
async def patch_connection(
    connection_id: int, body: ConnectionPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise NotFound("connection not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(conn, field, value)
    await audit.write(session, admin_id=admin.id, action="connection.update", entity="connection",
                       entity_id=conn.id, after=updates)
    location = await session.get(Location, conn.location_id) if conn.location_id else None
    slots_used = await _connection_slots_used(session, conn.id)
    return _connection_view(
        conn,
        city=location.city if location else None,
        state=location.state_code if location else None,
        slots_used=slots_used,
    )


@router.post("/connections/sync")
async def sync_connections(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    from app.core.config import settings
    from app.services.provisioning.sync import sync_external_holds, sync_pool

    if not settings.feature_real_provisioning:
        return {"synced": False, "detail": "real provisioning disabled (mock mode)"}
    result = await sync_pool(session)
    # The button's promise is "make this screen match iproxy right now" — and holds are
    # part of the screen. Without this walk a phone freed in the iproxy console stayed
    # "Held in iproxy" here for up to five minutes until the cron's own pass reached it,
    # which on 2026-08-19 read as the button doing nothing: the client freed a phone,
    # pressed Sync now, and watched the stale hold sit there.
    holds = await sync_external_holds(session)
    result = {**result, "holds": holds}
    await audit.write(
        session, admin_id=admin.id, action="connection.sync", entity="pool",
        entity_id="iproxy", after=result,
    )
    return {"synced": True, **result}


@router.get("/pool/summary")
async def pool_summary(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    """Pool health in three buckets that always add up to the whole pool.

    The old counts left connections out. `offline` matched only `online_status='offline'`,
    so a phone reporting 'unknown' — which is what iproxy sends when it has not heard from
    a device — landed in no bucket at all, and neither did an online phone an operator had
    marked unsellable. On the live pool that was two of three connections counted nowhere,
    while their cards on the same screen read "Offline".

    So the buckets are defined by what an operator can do with a connection, and every
    connection falls in exactly one, tested in this order:
      busy        — an access is live on it. Sold capacity, whether or not the phone is
                    answering right now; a device dropping off does not un-sell it.
      held        — occupied by a proxy-access created inside the iproxy console rather
                    than sold by us. Its own bucket because the answer to it is different
                    from every other: somebody has to go into iproxy and release it, and
                    until they do it earns nothing while looking like stock.
      free        — sellable, online, and nothing on it either way. What the allocator can
                    hand out this second, and the only number that answers "can we sell?".
      unavailable — everything else: offline, silent, or withheld by an operator.

    Busy wins over held: if we sold it, the fact that iproxy also lists an access on it is
    our own access being reported back, not a stranger's.
    """
    rows = await session.execute(
        text(
            """
            SELECT
                l.city,
                l.state_code,
                c.carrier,
                count(*) AS total,
                count(*) FILTER (
                    WHERE c.is_sellable AND c.online_status = 'online'
                      AND c.external_access_count = 0
                      AND NOT EXISTS (
                        SELECT 1 FROM accesses a
                        WHERE a.connection_id = c.id
                          AND a.status IN ('provisioning','active','expiring'))
                ) AS free,
                count(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1 FROM accesses a
                        WHERE a.connection_id = c.id
                          AND a.status IN ('provisioning','active','expiring'))
                ) AS busy,
                count(*) FILTER (
                    WHERE c.external_access_count > 0
                      AND NOT EXISTS (
                        SELECT 1 FROM accesses a
                        WHERE a.connection_id = c.id
                          AND a.status IN ('provisioning','active','expiring'))
                ) AS held
            FROM connections c
            LEFT JOIN locations l ON l.id = c.location_id
            GROUP BY l.city, l.state_code, c.carrier
            ORDER BY l.city NULLS LAST, c.carrier NULLS LAST
            """
        )
    )
    cities: list[dict[str, Any]] = []
    slots_total = slots_used = slots_free = slots_held = slots_unavailable = 0
    for city, state, carrier, total, free, busy, held in rows:
        total, free, busy, held = int(total), int(free), int(busy), int(held)
        # Derived, never counted separately: whatever is neither sold, held in iproxy nor
        # sellable is unavailable by definition, so the four can never fail to cover the
        # pool. free already excludes held (see the query), so there is no double count.
        unavailable = total - busy - free - held
        slots_total += total
        slots_used += busy
        slots_free += free
        slots_held += held
        slots_unavailable += unavailable
        cities.append(
            {
                "city": city,
                "state": state,
                "carrier": carrier,
                "slots_total": total,
                "slots_used": busy,
                # Named for what they are. The previous `online_nodes` meant free+busy while
                # its only consumer (the dashboard map) read it as "online and not full",
                # which made the map's "full" state unreachable arithmetic.
                "nodes_free": free,
                "nodes_busy": busy,
                "nodes_held": held,
                "nodes_unavailable": unavailable,
            }
        )
    return {
        "slots_total": slots_total,
        "slots_used": slots_used,
        "slots_free": slots_free,
        "slots_held": slots_held,
        "slots_unavailable": slots_unavailable,
        "cities": cities,
    }


# ── accesses (packages) ─────────────────────────────────────────────────
async def _revoked_by_map(session: DbSession, access_ids: Sequence[int]) -> dict[int, str]:
    """Who revoked each access — the actor on its latest `revoked` event.

    The name is not on the access itself: `revoke_reason` records *why*, and the event log
    records *who*, so answering "who cut this customer off, and what did they say" needs
    both. One query for the page rather than one per row, matching the connection and order
    lookups beside it.
    """
    ids = [aid for aid in access_ids if aid is not None]
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(AccessEvent.access_id, AccessEvent.actor)
            .where(AccessEvent.access_id.in_(ids), AccessEvent.type == "revoked")
            .distinct(AccessEvent.access_id)
            .order_by(AccessEvent.access_id, AccessEvent.created_at.desc())
        )
    ).all()
    admin_ids = [
        int(actor.split(":", 1)[1])
        for _, actor in rows
        if actor.startswith("admin:") and actor.split(":", 1)[1].isdigit()
    ]
    names = await _admin_display_map(session, admin_ids)
    out: dict[int, str] = {}
    for access_id, actor in rows:
        if actor.startswith("admin:") and actor.split(":", 1)[1].isdigit():
            # Falls back to the raw actor when the account has since been deleted — the
            # row outlives the account precisely so entries like this keep their name.
            out[access_id] = names.get(int(actor.split(":", 1)[1]), actor)
        else:
            out[access_id] = actor  # 'system' (expiry sweeper) or 'user'
    return out


def _access_view(
    a: Access,
    *,
    user_display: str,
    city: str | None,
    carrier: str | None,
    order_public_id: str | None = None,
    order_number: int | None = None,
    connection: str | None = None,
    connection_name: str | None = None,
    revoked_by: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(a.public_id),
        "user": user_display,
        "status": a.status,
        # Why this access ended, and at whose hand. The reason has been collected in a
        # required field on the revoke dialog since launch and was then readable nowhere —
        # an operator typed a justification into a box that only ever wrote to a column
        # nothing selected. "Expired" also stamps revoked_at, so a null reason there means
        # time ran out rather than somebody deciding.
        "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
        "revoke_reason": a.revoke_reason,
        "revoked_by": revoked_by,
        "city": city,
        "carrier": carrier,
        "ip": None,
        # Which physical phone is serving this access. Support reads it out when they open
        # the same connection in the iproxy console — without it, matching a customer's
        # complaint to a device meant guessing from city and carrier alone.
        "connection_id": connection,
        "connection_name": connection_name,
        # None = off; the interval is the on/off state (see models/access.py).
        "auto_rotate_minutes": a.auto_rotate_minutes,
        "tariff_code": a.tariff_code,
        # The order this access was bought with, twice over. The number is what an operator
        # reads out loud and types into a search; the public id is what every action takes,
        # and it stays a random UUID because /pay/{public_id} is an unauthenticated link
        # whose whole defence is being unguessable.
        "order_number": order_number,
        "order_public_id": order_public_id,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "created_at": a.created_at.isoformat(),
    }


async def _access_extras(session: DbSession, a: Access) -> dict[str, Any]:
    """The `_access_view` keyword arguments that need a lookup, for the single-object
    mutation endpoints below (list_admin_accesses bulk-joins instead).

    Returned as kwargs rather than a tuple: it has grown twice now, and a positional
    5-tuple unpacked at four call sites is one reordering away from a silent bug."""
    user = await session.get(User, a.user_id)
    conn = await session.get(Connection, a.connection_id)
    city: str | None = None
    carrier = conn.carrier if conn else None
    if conn is not None and conn.location_id is not None:
        loc = await session.get(Location, conn.location_id)
        city = loc.city if loc else None
    order = await session.get(Order, a.order_id)
    return {
        "user_display": _user_display(user),
        "city": city,
        "carrier": carrier,
        "order_public_id": str(order.public_id) if order else None,
        "order_number": order.id if order else None,
        "connection": conn.iproxy_connection_id if conn else None,
        "connection_name": conn.name if conn else None,
        "revoked_by": (await _revoked_by_map(session, [a.id])).get(a.id),
    }


@router.get("/accesses")
async def list_admin_accesses(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    city: str | None = None,
    user: str | None = None,
    user_id: int | None = None,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
    expiring: bool = False,
    expiring_24h: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Issued accesses. ``q`` searches every column the table shows except the dates.

    The screen used to have a box for the city and another for the user, which asks the
    operator to classify the string in their hand before they can look for it. `city` and
    `user` still work — the dossier and saved links use them — but the console sends `q`.
    """
    stmt = select(Access)
    count_stmt = select(func.count()).select_from(Access)
    if status:
        stmt = stmt.where(Access.status == status)
        count_stmt = count_stmt.where(Access.status == status)
    if user_id:
        stmt = stmt.where(Access.user_id == user_id)
        count_stmt = count_stmt.where(Access.user_id == user_id)
    if user:
        # Free-text match on @handle / first name / numeric telegram id — this is what
        # the admin "User" filter box sends (the frontend passes ?user=..., not user_id).
        term = user.strip().lstrip("@")
        clauses: list[ColumnElement[bool]] = [
            User.tg_username.ilike(f"%{term}%"),
            User.first_name.ilike(f"%{term}%"),
        ]
        if term.isdigit():
            clauses.append(User.tg_user_id == int(term))
        match_ids = select(User.id).where(or_(*clauses))
        stmt = stmt.where(Access.user_id.in_(match_ids))
        count_stmt = count_stmt.where(Access.user_id.in_(match_ids))
    if city:
        conn_ids = select(Connection.id).join(
            Location, Location.id == Connection.location_id
        ).where(Location.city.ilike(f"%{city}%"))
        stmt = stmt.where(Access.connection_id.in_(conn_ids))
        count_stmt = count_stmt.where(Access.connection_id.in_(conn_ids))
    if since:
        stmt = stmt.where(Access.created_at >= _parse_day(since))
        count_stmt = count_stmt.where(Access.created_at >= _parse_day(since))
    if before:
        end = _parse_day(before) + timedelta(days=1)
        stmt = stmt.where(Access.created_at < end)
        count_stmt = count_stmt.where(Access.created_at < end)
    search = _search_condition(
        q,
        [
            Access.status,
            Access.tariff_code,
            _sub(User.tg_username, User.id == Access.user_id),
            _sub(User.first_name, User.id == Access.user_id),
            _sub(cast(User.tg_user_id, String), User.id == Access.user_id),
            _sub(Connection.carrier, Connection.id == Access.connection_id),
            # Two tables away, so one subquery that joins rather than two that nest.
            # Nesting `_sub` inside `_sub` reads correctly and is not: the inner query
            # correlates against the subquery immediately around it, `accesses` is not in
            # scope there, and SQLAlchemy quietly adds it to the inner FROM. That returns
            # one row per access — invisible with a single record on the page, and
            # "more than one row returned by a subquery" the moment there are two.
            select(Location.city)
            .select_from(Connection)
            .join(Location, Location.id == Connection.location_id)
            .where(Connection.id == Access.connection_id)
            .scalar_subquery(),
        ],
        # The two numbers on this screen, both matched whole: the order number the Order
        # column shows, and a telegram id when somebody pastes a full one.
        number_columns=[Access.order_id, _sub(User.tg_user_id, User.id == Access.user_id)],
        # A customer quoting their order id pastes the whole thing, so it still has to find
        # the access it paid for — but never as a fragment of digits.
        opaque_columns=[_sub(cast(Order.public_id, String), Order.id == Access.order_id)],
    )
    if search is not None:
        stmt = stmt.where(search)
        count_stmt = count_stmt.where(search)
    if expiring or expiring_24h:
        cutoff = _utcnow() + timedelta(hours=24)
        stmt = stmt.where(
            Access.status.in_(("active", "expiring")), Access.expires_at <= cutoff
        )
        count_stmt = count_stmt.where(
            Access.status.in_(("active", "expiring")), Access.expires_at <= cutoff
        )
    stmt = stmt.order_by(Access.created_at.desc())

    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    user_display_map = await _user_display_map(session, [a.user_id for a in rows])
    connection_ids = {a.connection_id for a in rows}
    conn_lookup: dict[int, tuple[str | None, str | None, str | None, str | None]] = {}
    if connection_ids:
        conn_rows = (
            await session.execute(
                select(
                    Connection.id,
                    Connection.carrier,
                    Location.city,
                    Connection.iproxy_connection_id,
                    Connection.name,
                )
                .outerjoin(Location, Location.id == Connection.location_id)
                .where(Connection.id.in_(connection_ids))
            )
        ).all()
        for cid, carrier, city_val, iproxy_id, conn_name in conn_rows:
            conn_lookup[cid] = (city_val, carrier, iproxy_id, conn_name)

    # One query for the page's orders rather than one per row — the same shape as the
    # connection lookup above.
    order_lookup: dict[int, str] = {}
    order_ids = {a.order_id for a in rows}
    if order_ids:
        order_lookup = {
            oid: str(pub)
            for oid, pub in (
                await session.execute(
                    select(Order.id, Order.public_id).where(Order.id.in_(order_ids))
                )
            ).all()
        }

    # Only the revoked rows need an actor, and on a page of live accesses that is usually
    # none of them — so the lookup is skipped rather than run over the whole page.
    revoked_by = await _revoked_by_map(session, [a.id for a in rows if a.status == "revoked"])

    empty_conn: tuple[str | None, str | None, str | None, str | None] = (None, None, None, None)
    items = [
        _access_view(
            a,
            user_display=user_display_map.get(a.user_id, "—"),
            city=conn_lookup.get(a.connection_id, empty_conn)[0],
            carrier=conn_lookup.get(a.connection_id, empty_conn)[1],
            connection=conn_lookup.get(a.connection_id, empty_conn)[2],
            connection_name=conn_lookup.get(a.connection_id, empty_conn)[3],
            order_public_id=order_lookup.get(a.order_id),
            # The order's own key is the sequential number — no second lookup for it.
            order_number=a.order_id,
            revoked_by=revoked_by.get(a.id),
        )
        for a in rows
    ]
    return {"items": items, "total": total}


async def _get_access(session: DbSession, access_id: str) -> Access:
    access = await session.scalar(select(Access).where(Access.public_id == access_id))
    if access is None:
        raise NotFound("access not found")
    return access


class RevokeBody(BaseModel):
    reason: str


@router.post("/accesses/{access_id}/revoke")
async def admin_revoke_access(
    access_id: str, body: RevokeBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    access = await _get_access(session, access_id)
    await revoke_access(session, access=access, reason=body.reason, actor=f"admin:{admin.id}")
    await audit.write(session, admin_id=admin.id, action="access.revoke", entity="access",
                       entity_id=access.id, after={"reason": body.reason})
    extras = await _access_extras(session, access)
    return _access_view(access, **extras)


class ExtendAdminBody(BaseModel):
    minutes: int


@router.post("/accesses/{access_id}/extend")
async def admin_extend_access(
    access_id: str, body: ExtendAdminBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    access = await _get_access(session, access_id)
    await extend_access(session, access=access, minutes=body.minutes)
    await audit.write(session, admin_id=admin.id, action="access.extend", entity="access",
                       entity_id=access.id, after={"minutes": body.minutes})
    extras = await _access_extras(session, access)
    return _access_view(access, **extras)


class AutoRotateAdminBody(BaseModel):
    enabled: bool
    minutes: int | None = Field(default=None, ge=1, le=1440)


# Support-side control over the buyer's rotation schedule. Not on the packages table —
# a column of "Off" on every row answered a question that screen is not for — but on the
# client's own dossier, next to the access it applies to, which is where "make mine rotate
# every 30 minutes" arrives as a message from that client.
#
# Deliberately not a one-shot rotate: doing that from here changes a live customer's
# address under them with nothing on their side to explain it.
@router.put("/accesses/{access_id}/auto-rotate")
async def admin_set_auto_rotate(
    access_id: str, body: AutoRotateAdminBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    access = await _get_access(session, access_id)
    if access.status not in ("active", "expiring"):
        raise Conflict("only a live access can rotate")
    if body.enabled and body.minutes is None:
        raise ValidationError("choose how often to rotate")
    access.auto_rotate_minutes = body.minutes if body.enabled else None
    await audit.write(session, admin_id=admin.id, action="access.auto_rotate", entity="access",
                       entity_id=access.id, after={"minutes": access.auto_rotate_minutes})
    extras = await _access_extras(session, access)
    return _access_view(access, **extras)


class ReissueBody(BaseModel):
    connection_id: int | None = None


@router.post("/accesses/{access_id}/reissue")
async def admin_reissue_access(
    access_id: str, body: ReissueBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    access = await _get_access(session, access_id)
    await swap_access(session, access=access, location_id=None, carrier=None)
    await enqueue(
        session, user_id=access.user_id, template_code="access_reissued",
        payload={"access_public_id": str(access.public_id)},
    )
    await audit.write(session, admin_id=admin.id, action="access.reissue", entity="access",
                       entity_id=access.id)
    extras = await _access_extras(session, access)
    return _access_view(access, **extras)


# ── orders / payments ────────────────────────────────────────────────────
def _order_view(o: Order, *, user_display: str, provider: str | None) -> dict[str, Any]:
    return {
        "id": str(o.public_id),
        # What the operator sees and says. The id stays the UUID because every action takes
        # it and /pay/{public_id} is unauthenticated — a countable number there would let
        # anyone walk the orders.
        "number": o.id,
        "user": user_display,
        "status": o.status,
        "provider": provider,
        "amount_usd": float(o.amount_usd),
        # Which plan, and how many of it — an order for $85 and one for $255 are the same
        # plan bought differently, and the amount alone does not say which.
        "tariff_code": o.tariff_code,
        "quantity": int(o.quantity or 1),
        "created_at": o.created_at.isoformat(),
    }


async def _order_extras(session: DbSession, o: Order) -> tuple[str, str | None]:
    """Resolve (user_display, provider) for a single order (via its most recent invoice)."""
    user = await session.get(User, o.user_id)
    provider = await session.scalar(
        select(Invoice.provider)
        .where(Invoice.order_id == o.id)
        .order_by(Invoice.created_at.desc())
        .limit(1)
    )
    return _user_display(user), provider


async def _bulk_order_providers(session: DbSession, order_ids: Sequence[int]) -> dict[int, str]:
    """Bulk-resolve each order's most recent invoice provider (avoids N+1 in list endpoints)."""
    if not order_ids:
        return {}
    rows = (
        await session.execute(
            select(Invoice.order_id, Invoice.provider)
            .where(Invoice.order_id.in_(order_ids))
            .order_by(Invoice.created_at.desc())
        )
    ).all()
    provider_by_order: dict[int, str] = {}
    for order_id, provider in rows:
        provider_by_order.setdefault(order_id, provider)  # first hit wins = most recent (desc)
    return provider_by_order


@router.get("/orders")
async def list_orders(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    provider: str | None = None,
    tariff: str | None = None,
    user_id: int | None = None,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Orders, filtered and sorted server-side.

    This list had no search and no filters at all, so "find the order this customer is
    asking about" meant paging through everything or opening clients one at a time. The
    filters mirror the payments screen deliberately — an operator moving between the two
    should not have to learn a second set of controls.
    """
    stmt = select(Order)
    count_stmt = select(func.count()).select_from(Order)
    if status:
        stmt = stmt.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)
    if tariff:
        stmt = stmt.where(Order.tariff_code == tariff)
        count_stmt = count_stmt.where(Order.tariff_code == tariff)
    if since:
        stmt = stmt.where(Order.created_at >= _parse_day(since))
        count_stmt = count_stmt.where(Order.created_at >= _parse_day(since))
    if before:
        # inclusive end-of-day, same as everywhere else: "to 5 Aug" means through the 5th
        end = _parse_day(before) + timedelta(days=1)
        stmt = stmt.where(Order.created_at < end)
        count_stmt = count_stmt.where(Order.created_at < end)
    if q and q.strip():
        needle_raw = q.strip()
        if needle_raw.lstrip("#").isdigit():
            # The order number in this table's own first column — what a buyer quotes.
            cond: ColumnElement[bool] = Order.id == int(needle_raw.lstrip("#"))
        else:
            # A handle off a Telegram message, or a plan code. Both are things an operator
            # is holding when they arrive here; neither had anywhere to be typed.
            needle = f"%{needle_raw.lstrip('@')}%"
            cond = or_(
                Order.user_id.in_(select(User.id).where(User.tg_username.ilike(needle))),
                Order.tariff_code.ilike(needle),
            )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if user_id:
        stmt = stmt.where(Order.user_id == user_id)
        count_stmt = count_stmt.where(Order.user_id == user_id)
    if date_from:
        stmt = stmt.where(Order.created_at >= date_from)
        count_stmt = count_stmt.where(Order.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Order.created_at <= date_to)
        count_stmt = count_stmt.where(Order.created_at <= date_to)
    if provider:
        inv_order_ids = select(Invoice.order_id).where(Invoice.provider == provider)
        stmt = stmt.where(Order.id.in_(inv_order_ids))
        count_stmt = count_stmt.where(Order.id.in_(inv_order_ids))

    sort_col = {
        "created_at": Order.created_at,
        "amount_usd": Order.amount_usd,
        "status": Order.status,
        "number": Order.id,
    }.get(sort, Order.created_at)
    direction = sort_col.asc() if order == "asc" else sort_col.desc()
    # id as the tiebreaker: orders written in the same second share created_at, and without
    # it their order shifts between pages so rows get skipped or repeated.
    stmt = stmt.order_by(direction, Order.id.desc())

    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    user_display_map = await _user_display_map(session, [o.user_id for o in rows])
    provider_by_order = await _bulk_order_providers(session, [o.id for o in rows])
    items = [
        _order_view(
            o,
            user_display=user_display_map.get(o.user_id, "—"),
            provider=provider_by_order.get(o.id),
        )
        for o in rows
    ]
    return {"items": items, "total": total}


async def _get_order(session: DbSession, order_id: str) -> Order:
    order = await session.scalar(select(Order).where(Order.public_id == order_id))
    if order is None:
        raise NotFound("order not found")
    return order


@router.get("/orders/{order_id}")
async def order_detail(order_id: str, admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    order = await _get_order(session, order_id)
    invoice = await session.scalar(select(Invoice).where(Invoice.order_id == order.id))
    events: Sequence[PaymentEvent] = []
    if invoice is not None:
        events = (
            (await session.execute(
                select(PaymentEvent)
                .where(PaymentEvent.provider_invoice_id == invoice.provider_invoice_id)
                .order_by(PaymentEvent.received_at.desc())
            )).scalars().all()
        )
    user = await session.get(User, order.user_id)
    return {
        **_order_view(
            order,
            user_display=_user_display(user),
            provider=invoice.provider if invoice is not None else None,
        ),
        "invoice": (
            {
                "id": str(invoice.id),
                "amount_usd": float(invoice.amount_usd),
                "currency": invoice.crypto_currency or "USD",
                "wallet_address": invoice.pay_address,
                "memo": None,
            }
            if invoice is not None
            else None
        ),
        "events": [
            {
                "id": str(e.id),
                "type": str((e.payload or {}).get("status") or e.processing_result or "event"),
                "message": f"{e.provider} webhook: {e.processing_result or 'received, not yet processed'}",
                "created_at": e.received_at.isoformat(),
            }
            for e in events
        ],
    }


@router.get("/payments/manual-review")
async def manual_review_orders(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Order).where(Order.status == "manual_review").order_by(Order.created_at)
        )
    ).scalars().all()
    user_display_map = await _user_display_map(session, [o.user_id for o in rows])
    provider_by_order = await _bulk_order_providers(session, [o.id for o in rows])
    items = [
        _order_view(
            o,
            user_display=user_display_map.get(o.user_id, "—"),
            provider=provider_by_order.get(o.id),
        )
        for o in rows
    ]
    return {"items": items, "total": len(items)}


# ── on-chain deposit ledger (observability + audit; append-only, doc 15) ──
# Deposits still waiting for a human decision — the operator's actual queue, and what the
# "Unmatched" badge counts.
#
# `orphaned` is deliberately absent: it is what a write-off produces, so it means the
# decision has been made. Counting it kept a resolved deposit in the queue forever, which
# is the same "it never goes down" problem the badge already had for another reason.
# Reversing a write-off is still possible (see manual_resolution._RESOLVABLE) — that is a
# capability, not outstanding work.
_NEEDS_DECISION_STATUSES = ("unmatched", "underpaid", "expired_deposit")


def _latest_ledger_ids() -> Select[tuple[int]]:
    """Ids of the newest row per on-chain transfer — each deposit's current state.

    Keyed on max(id) rather than the `v_deposit_current` view: that view breaks ties on
    `created_at`, and a manual resolution writes `matched` + `paid` in the same instant, so
    it can pick either one. Ids are monotonic and never ambiguous.
    """
    return (
        select(func.max(OnchainDepositLedger.id))
        .group_by(OnchainDepositLedger.txid, OnchainDepositLedger.log_index)
    )


def _parse_day(value: str) -> datetime:
    """A ``YYYY-MM-DD`` filter bound as midnight UTC.

    Rejects garbage rather than ignoring it: a dropped date filter returns the unfiltered
    list, and the operator reads that as the answer to the question they asked.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise ValidationError(f"Invalid date '{value}', expected YYYY-MM-DD") from None


def _ledger_view(
    row: OnchainDepositLedger,
    *,
    user_display: str | None,
    is_current: bool = True,
    order_public_id: str | None = None,
    order_number: int | None = None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        # Is this row the deposit's *current* state, or a historical snapshot? The ledger
        # is append-only, so a row that once said "unmatched" says so forever — offering
        # "Resolve" on it after the deposit was settled just produces a 409.
        "is_current": is_current,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "chain": row.chain,
        "asset": row.asset,
        "network": row.network,
        "txid": row.txid,
        "log_index": row.log_index,
        "from_address": row.from_address,
        "to_address": row.to_address,
        "amount": str(row.amount),
        "amount_usd": float(row.amount_usd) if row.amount_usd is not None else None,
        "confirmations": row.confirmations,
        "block_number": row.block_number,
        "invoice_id": str(row.invoice_id) if row.invoice_id is not None else None,
        # The identifier an operator can actually act on: the Orders screen finds it and
        # the resolve dialog takes it. `invoice_id` is an internal primary key with nowhere
        # to look it up. The number beside it is the readable half.
        "order_number": order_number,
        "order_public_id": order_public_id,
        "user": user_display,
        "user_id": str(row.user_id) if row.user_id is not None else None,
    }


@router.get("/payments/ledger")
async def list_deposit_ledger(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    chain: str | None = None,
    asset: str | None = None,
    invoice_id: int | None = None,
    txid: str | None = None,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    current_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """On-chain deposit ledger — filtered and sorted server-side.

    ``current_only`` (default) collapses each transfer to its newest row — what an
    operator means by "show me the unmatched ones". Without it, filtering by a status
    returns every row that ever held it, so a deposit resolved an hour ago still shows up
    under Unmatched forever. Turn it off for the full append-only audit trail.

    Everything else exists for one job: after a year of transfers, answering "a customer
    is asking about a payment from three months ago". Scrolling is not an answer, so the
    lookups a person actually has to hand — a transaction hash, an address, a date range —
    all filter here rather than in the browser over one page of rows.
    """
    stmt = select(OnchainDepositLedger)
    count_stmt = select(func.count()).select_from(OnchainDepositLedger)
    conds: list[ColumnElement[bool]] = []
    if current_only:
        conds.append(OnchainDepositLedger.id.in_(_latest_ledger_ids()))
    if status:
        conds.append(OnchainDepositLedger.status == status)
    if chain:
        conds.append(OnchainDepositLedger.chain == chain)
    if asset:
        conds.append(OnchainDepositLedger.asset == asset)
    if invoice_id:
        conds.append(OnchainDepositLedger.invoice_id == invoice_id)
    if txid:
        conds.append(OnchainDepositLedger.txid == txid)
    if since:
        conds.append(OnchainDepositLedger.created_at >= _parse_day(since))
    if before:
        # inclusive end-of-day: a person picking "to 5 Aug" means through the 5th
        conds.append(OnchainDepositLedger.created_at < _parse_day(before) + timedelta(days=1))
    if q and q.strip():
        from app.services.payments.onchain.assets import CHAINS, SPECS

        needle_raw = q.strip()
        # A coin or a chain name is matched by equality. Operators type "BTC" long before
        # they paste a hash, and against the substring branch alone that query returned the
        # whole table — an answer to a question nobody asked. Equality on these two short
        # columns is also why this field no longer demands a minimum length: the length
        # floor existed to keep one-character queries from scanning every hash.
        if needle_raw.lower() in CHAINS:
            conds.append(OnchainDepositLedger.chain == needle_raw.lower())
        elif needle_raw.upper() in {spec.asset for spec in SPECS.values()}:
            conds.append(OnchainDepositLedger.asset == needle_raw.upper())
        elif needle_raw.lstrip("#").isdigit():
            # The order number shown in this table's own Order column. Matched whole and
            # through the invoice, because that is the only link a deposit has to an order.
            # It wins over the substring branch below: nobody hunts a transaction hash by
            # typing four digits of it, and plenty of people paste an order number.
            conds.append(
                OnchainDepositLedger.invoice_id.in_(
                    select(Invoice.id).where(Invoice.order_id == int(needle_raw.lstrip("#")))
                )
            )
        else:
            # Otherwise it is one of the three things anyone actually pastes: a transaction
            # hash, the address it came from, or the address it went to. Separate inputs per
            # column would make the operator guess which one they are holding.
            needle = f"%{needle_raw}%"
            conds.append(
                or_(
                    OnchainDepositLedger.txid.ilike(needle),
                    OnchainDepositLedger.from_address.ilike(needle),
                    OnchainDepositLedger.to_address.ilike(needle),
                )
            )
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    sort_col = {
        "created_at": OnchainDepositLedger.created_at,
        "amount": OnchainDepositLedger.amount,
        "amount_usd": OnchainDepositLedger.amount_usd,
        "status": OnchainDepositLedger.status,
        "chain": OnchainDepositLedger.chain,
    }.get(sort, OnchainDepositLedger.created_at)
    direction = sort_col.asc() if order == "asc" else sort_col.desc()
    # id as the tiebreaker: rows written in the same transaction share created_at exactly,
    # and without it their order shifts between pages and rows get skipped or repeated.
    stmt = stmt.order_by(direction, OnchainDepositLedger.id.desc())
    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    user_display_map = await _user_display_map(session, [r.user_id for r in rows])
    # Newest row per (txid, log_index) among the ones on this page's transactions — the
    # deposit's current state. Anything older is history and must not offer actions.
    current_ids: set[int] = set()
    if rows:
        latest = await session.execute(
            select(
                OnchainDepositLedger.txid,
                OnchainDepositLedger.log_index,
                func.max(OnchainDepositLedger.id),
            )
            .where(OnchainDepositLedger.txid.in_({r.txid for r in rows}))
            .group_by(OnchainDepositLedger.txid, OnchainDepositLedger.log_index)
        )
        current_ids = {int(row_id) for _, _, row_id in latest}
    # invoice id -> the order's public id, in one query for the whole page. The ledger
    # stores the invoice, but the invoice number means nothing to anyone: the buyer quotes
    # an order id, the Orders screen searches by it, and the resolve dialog accepts it.
    order_ids: dict[int, tuple[str, int]] = {}
    invoice_ids = {r.invoice_id for r in rows if r.invoice_id is not None}
    if invoice_ids:
        pairs = await session.execute(
            select(Invoice.id, Order.public_id, Order.id)
            .join(Order, Order.id == Invoice.order_id)
            .where(Invoice.id.in_(invoice_ids))
        )
        order_ids = {int(inv_id): (str(pub), num) for inv_id, pub, num in pairs}
    items = [
        _ledger_view(
            r,
            user_display=user_display_map.get(r.user_id),
            is_current=r.id in current_ids,
            order_public_id=order_ids.get(r.invoice_id, (None, None))[0] if r.invoice_id else None,
            order_number=order_ids.get(r.invoice_id, (None, None))[1] if r.invoice_id else None,
        )
        for r in rows
    ]
    return {"items": items, "total": total}


@router.get("/payments/invoices")
async def list_invoices(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    chain: str | None = None,
    asset: str | None = None,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Every invoice raised, whether or not money ever arrived for it.

    The ledger beside this one answers "what came in"; nothing answered "what is owed".
    An operator wanting the invoices still waiting had to open clients one at a time and
    read each dossier, which is not a list anybody can work from — and the awaiting ones
    are exactly the set worth watching, since that is where a customer sits with an
    address in front of them.

    Same filters as the ledger, because the operator arrives with the same things in hand:
    an order number, a coin, a date range.
    """
    stmt = select(Invoice, Order).join(Order, Order.id == Invoice.order_id)
    count_stmt = select(func.count()).select_from(Invoice).join(Order, Order.id == Invoice.order_id)
    conds: list[ColumnElement[bool]] = []
    if status:
        # "awaiting" is the question this screen exists for: everything raised where the
        # money has not landed, across the three statuses that mean it.
        if status == "awaiting":
            conds.append(Invoice.status.in_(("created", "pending", "confirming")))
        else:
            conds.append(Invoice.status == status)
    if chain:
        conds.append(Invoice.chain == chain)
    if asset:
        conds.append(Invoice.crypto_currency == asset.upper())
    if since:
        conds.append(Invoice.created_at >= _parse_day(since))
    if before:
        conds.append(Invoice.created_at < _parse_day(before) + timedelta(days=1))
    if q and q.strip():
        from app.services.payments.onchain.assets import CHAINS, SPECS

        needle_raw = q.strip()
        if needle_raw.lower() in CHAINS:
            conds.append(Invoice.chain == needle_raw.lower())
        elif needle_raw.upper() in {spec.asset for spec in SPECS.values()}:
            conds.append(Invoice.crypto_currency == needle_raw.upper())
        elif needle_raw.lstrip("#").isdigit():
            # The order number in this table's own column — what a buyer quotes.
            conds.append(Order.id == int(needle_raw.lstrip("#")))
        else:
            # A handle, or the receiving address off a screenshot the buyer sent.
            needle = f"%{needle_raw}%"
            conds.append(
                or_(
                    Invoice.pay_address.ilike(needle),
                    Invoice.matched_txid.ilike(needle),
                    Order.user_id.in_(
                        select(User.id).where(User.tg_username.ilike(needle.lstrip("@")))
                    ),
                )
            )
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    sort_col = {
        "created_at": Invoice.created_at,
        "expires_at": Invoice.expires_at,
        "amount_usd": Invoice.amount_usd,
        "status": Invoice.status,
        "chain": Invoice.chain,
    }.get(sort, Invoice.created_at)
    direction = sort_col.asc() if order == "asc" else sort_col.desc()
    stmt = stmt.order_by(direction, Invoice.id.desc())
    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
    user_display_map = await _user_display_map(session, [o.user_id for _inv, o in rows])
    items = [
        {
            "id": str(inv.id),
            "order_number": order_row.id,
            "order_public_id": str(order_row.public_id),
            "user": user_display_map.get(order_row.user_id),
            "status": inv.status,
            "order_status": order_row.status,
            "amount_usd": float(inv.amount_usd),
            "crypto_amount": float(inv.crypto_amount) if inv.crypto_amount is not None else None,
            "crypto_currency": inv.crypto_currency,
            "crypto_network": inv.crypto_network,
            "chain": inv.chain,
            "pay_address": inv.pay_address,
            "quantity": int(order_row.quantity or 1),
            "tariff_code": order_row.tariff_code,
            "created_at": inv.created_at.isoformat(),
            "expires_at": inv.expires_at.isoformat(),
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
        }
        for inv, order_row in rows
    ]
    return {"items": items, "total": total}


class AttachDeposit(BaseModel):
    order_public_id: str
    note: str | None = None


class WriteOffDeposit(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("/payments/ledger/{deposit_id}/candidates")
async def deposit_candidates(
    deposit_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Orders this parked deposit plausibly belongs to, closest amount first.

    Asking the operator to type an order id they have no way of knowing turns a two-click
    job into a hunt across screens — and a guessed id credits the wrong buyer. The rail and
    the receiving address are already known from the deposit, so the shortlist is derived
    rather than remembered.
    """
    row = await session.get(OnchainDepositLedger, deposit_id)
    if row is None:
        raise NotFound("deposit not found")

    invoices = list(
        await session.scalars(
            select(Invoice)
            .where(
                Invoice.provider == "onchain",
                Invoice.crypto_currency == row.asset,
                Invoice.crypto_network == row.network,
                Invoice.status.notin_(("paid",)),
            )
            .order_by(Invoice.id.desc())
            .limit(200)
        )
    )
    paid = Decimal(str(row.amount))
    out: list[dict[str, Any]] = []
    for inv in invoices:
        order = await session.get(Order, inv.order_id)
        if order is None or order.status not in ("awaiting_payment", "expired", "manual_review"):
            continue
        user = await session.get(User, order.user_id)
        expected = Decimal(str(inv.crypto_amount)) if inv.crypto_amount is not None else None
        out.append(
            {
                "order_public_id": str(order.public_id),
                "order_number": order.id,
                "order_status": order.status,
                "invoice_status": inv.status,
                "user": _user_display(user),
                "amount_usd": float(order.amount_usd),
                "crypto_amount": str(inv.crypto_amount) if expected is not None else None,
                "difference": str(abs(expected - paid)) if expected is not None else None,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
        )
    # Exact quote first, then near misses — the operator sees the obvious answer on top.
    out.sort(key=lambda c: Decimal(c["difference"]) if c["difference"] is not None else Decimal(10**9))
    return {"deposit_amount": str(paid), "asset": row.asset, "candidates": out[:10]}


@router.post("/payments/ledger/{deposit_id}/attach")
async def attach_deposit(
    deposit_id: int, body: AttachDeposit, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Credit a parked deposit to an order — the operator's way out of `unmatched`.

    Money authority applies: attaching a deposit hands over a paid product, so it sits
    under the same operator ceiling as refunds rather than being a free action.
    """
    from app.services.payments.onchain import manual_resolution

    row = await session.get(OnchainDepositLedger, deposit_id)
    if row is None:
        raise NotFound("deposit not found")
    return await manual_resolution.attach_to_order(
        session,
        deposit_id=deposit_id,
        order_public_id=body.order_public_id,
        operator_id=admin.id,
        note=body.note,
    )


@router.post("/payments/ledger/{deposit_id}/write-off")
async def write_off_deposit(
    deposit_id: int, body: WriteOffDeposit, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Close a parked deposit without crediting anyone. Appends, never edits."""
    from app.services.payments.onchain import manual_resolution

    return await manual_resolution.write_off(
        session, deposit_id=deposit_id, operator_id=admin.id, reason=body.reason
    )


@router.get("/payments/ledger/summary")
async def deposit_ledger_summary(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    """Counts by status + recent volume — the on-chain watcher observability panel."""
    by_status = (
        await session.execute(
            select(OnchainDepositLedger.status, func.count()).group_by(
                OnchainDepositLedger.status
            )
        )
    ).all()
    since = _utcnow() - timedelta(hours=24)
    events_24h = int(
        await session.scalar(
            select(func.count())
            .select_from(OnchainDepositLedger)
            .where(OnchainDepositLedger.created_at >= since)
        )
        or 0
    )
    return {
        "by_status": {status: int(count) for status, count in by_status},
        "events_24h": events_24h,
        # Deposits that are unmatched *right now*. Counting every row that ever said
        # "unmatched" made this number permanent: the ledger is append-only, so resolving
        # a deposit adds a row rather than changing the old one, and the badge sat at 2
        # forever while the queue was actually empty.
        "unmatched_total": int(
            await session.scalar(
                select(func.count())
                .select_from(OnchainDepositLedger)
                .where(
                    OnchainDepositLedger.status.in_(_NEEDS_DECISION_STATUSES),
                    OnchainDepositLedger.id.in_(_latest_ledger_ids()),
                )
            )
            or 0
        ),
    }


@router.get("/payments/reconciliation")
async def payment_reconciliation(
    admin: CurrentAdmin, session: DbSession, date: str | None = None
) -> dict[str, Any]:
    """Daily settlement check — did we miss (or over-credit) any payment? Defaults to today."""
    from datetime import date as date_cls

    from app.services.payments.reconciliation import reconcile_day

    day = date_cls.fromisoformat(date) if date else datetime.now(UTC).date()
    return await reconcile_day(session, day)


class ResolveBody(BaseModel):
    action: str  # 'approve' | 'fail' | 'refund'


@router.post("/orders/{order_id}/resolve")
async def resolve_order(
    order_id: str, body: ResolveBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    order = await _get_order(session, order_id)
    # This endpoint exists to clear the manual-review queue. Restricting it to that state
    # (and refusing to re-provision) is what stops one order from being turned into N live
    # accesses — the real defect here, independent of who calls it.
    if order.status != "manual_review":
        raise Conflict("only an order in manual_review can be resolved")
    if body.action == "approve":
        existing = await session.scalar(
            select(Access).where(
                Access.order_id == order.id, Access.status.in_(_ACTIVE_ACCESS)
            )
        )
        if existing is not None:
            raise Conflict("this order already has a live access")
        await provision_access(session, order=order)
    elif body.action == "fail":
        order.status = "cancelled"
    elif body.action == "refund":
        order.status = "refunded"
    else:
        raise ValidationError("action must be 'approve', 'fail', or 'refund'")
    await audit.write(session, admin_id=admin.id, action="order.resolve", entity="order",
                       entity_id=order.id, after={"action": body.action})
    user_display, provider = await _order_extras(session, order)
    return _order_view(order, user_display=user_display, provider=provider)


class RefundBody(BaseModel):
    amount_usd: float
    reason: str
    wallet_address: str | None = None
    tx_hash: str | None = None


@router.post("/orders/{order_id}/refund")
async def refund_order(
    order_id: str, body: RefundBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    order = await _get_order(session, order_id)
    if order.paid_at is None:
        raise ValidationError("cannot refund an order that was never paid")
    already_refunded = Decimal(
        str(
            await session.scalar(
                select(func.coalesce(func.sum(Refund.amount_usd), 0)).where(
                    Refund.order_id == order.id
                )
            )
            or 0
        )
    )
    if body.amount_usd <= 0 or already_refunded + Decimal(str(body.amount_usd)) > Decimal(
        str(order.amount_usd)
    ):
        raise ValidationError(
            "refund amount must be > 0 and total refunds must not exceed the order amount"
        )
    order.status = "refunded"

    active_access = await session.scalar(
        select(Access).where(Access.order_id == order.id, Access.status.in_(_ACTIVE_ACCESS))
    )
    if active_access is not None:
        await revoke_access(session, access=active_access, reason="refund", actor=f"admin:{admin.id}")

    refund = Refund(
        order_id=order.id,
        amount_usd=body.amount_usd,
        reason=body.reason,
        wallet_address=body.wallet_address,
        tx_hash=body.tx_hash,
        operator_id=admin.id,
    )
    session.add(refund)
    await session.flush()

    # claw back the referral accrual pro-rata to the refunded amount
    await referral.reverse(session, order=order, refund_amount_usd=Decimal(str(body.amount_usd)))

    await enqueue(
        session, user_id=order.user_id, template_code="refund_processed",
        payload={"order_public_id": str(order.public_id), "amount_usd": body.amount_usd},
    )
    await audit.write(session, admin_id=admin.id, action="order.refund", entity="order",
                       entity_id=order.id, after={"refund_id": refund.id,
                                                   "amount_usd": body.amount_usd})
    user_display, provider = await _order_extras(session, order)
    return {
        "order": _order_view(order, user_display=user_display, provider=provider),
        "refund_id": refund.id,
    }


class MarkPaidBody(BaseModel):
    reason: str


@router.post("/orders/{order_id}/mark-paid")
async def admin_mark_paid(
    order_id: str, body: MarkPaidBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    from app.services import orders as orders_svc

    order = await _get_order(session, order_id)
    await orders_svc.mark_paid(session, order=order, source="manual")
    await audit.write(session, admin_id=admin.id, action="order.mark_paid", entity="order",
                       entity_id=order.id, after={"reason": body.reason})
    user_display, provider = await _order_extras(session, order)
    return _order_view(order, user_display=user_display, provider=provider)


# ── requests (kanban) ────────────────────────────────────────────────────
def _request_view(r: Request, *, user_display: str) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "user": user_display,
        "subject": r.subject,
        "status": r.status,
        "assignee_id": str(r.assignee_id) if r.assignee_id is not None else None,
        "created_at": r.created_at.isoformat(),
    }


@router.get("/requests")
async def list_requests(
    admin: CurrentAdmin, session: DbSession, status: str | None = None
) -> dict[str, Any]:
    stmt = select(Request).order_by(Request.updated_at.desc())
    if status:
        stmt = stmt.where(Request.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    user_display_map = await _user_display_map(session, [r.user_id for r in rows])
    items = [
        _request_view(r, user_display=user_display_map.get(r.user_id, "—")) for r in rows
    ]
    return {"items": items, "total": len(items)}


class RequestPatch(BaseModel):
    status: str | None = None
    assignee_id: int | None = None


@router.patch("/requests/{request_id}")
async def patch_request(
    request_id: int, body: RequestPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    req = await session.get(Request, request_id)
    if req is None:
        raise NotFound("request not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(req, field, value)
    await audit.write(session, admin_id=admin.id, action="request.update", entity="request",
                       entity_id=req.id, after=updates)
    user = await session.get(User, req.user_id) if req.user_id is not None else None
    return _request_view(req, user_display=_user_display(user))


class RequestCommentBody(BaseModel):
    body: str


@router.post("/requests/{request_id}/comments", status_code=201)
async def add_request_comment(
    request_id: int, body: RequestCommentBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    req = await session.get(Request, request_id)
    if req is None:
        raise NotFound("request not found")
    comment = RequestComment(request_id=req.id, author_admin_id=admin.id, body=body.body)
    session.add(comment)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="request.comment", entity="request",
                       entity_id=req.id, after={"comment_id": comment.id})
    return {
        "id": str(comment.id),
        "body": comment.body,
        "author": admin.display_name,
        "created_at": comment.created_at.isoformat(),
    }


@router.get("/requests/{request_id}")
async def get_request(
    request_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    req = await session.get(Request, request_id)
    if req is None:
        raise NotFound("request not found")
    user = await session.get(User, req.user_id) if req.user_id is not None else None
    comments = (
        await session.execute(
            select(RequestComment)
            .where(RequestComment.request_id == req.id)
            .order_by(RequestComment.created_at.asc())
        )
    ).scalars().all()
    admin_map = await _admin_display_map(session, [c.author_admin_id for c in comments])
    return {
        **_request_view(req, user_display=_user_display(user)),
        "type": req.type,
        "body": req.body,
        "comments": [
            {
                "id": str(c.id),
                "body": c.body,
                "author": admin_map.get(c.author_admin_id, "—"),
                "created_at": c.created_at.isoformat(),
            }
            for c in comments
        ],
    }


# ── referrals ────────────────────────────────────────────────────────────
@router.get("/referrals/summary")
async def referrals_summary(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    """The five numbers above the referrals screen.

    It used to return the ledger grouped by status — `{"paid": 1.84}` — while the screen
    read `total_referrers`, `total_clicks` and three more that were never in there. Every
    card therefore showed zero, including "Paid out" on a day when money had been paid.
    """
    referred = User.referrer_user_id.is_not(None)
    # People who have actually brought somebody, not everyone holding a code — every user
    # gets a code the moment they open the bot, so counting codes would count the userbase.
    referrers = select(func.count(distinct(User.referrer_user_id))).where(referred)
    attached = select(func.count()).select_from(User).where(referred)
    clicks = select(func.coalesce(func.sum(User.referral_clicks), 0))
    paid = select(func.coalesce(func.sum(ReferralLedger.amount_usd), 0)).where(
        ReferralLedger.status == "paid"
    )
    # The same two states the payouts queue lists, so the card and the table under it
    # cannot disagree about how much work is waiting.
    pending = (
        select(func.count())
        .select_from(Payout)
        .where(Payout.status.in_(("requested", "approved")))
    )
    return {
        "total_referrers": int(await session.scalar(referrers) or 0),
        "total_clicks": int(await session.scalar(clicks) or 0),
        "total_attached": int(await session.scalar(attached) or 0),
        "total_paid_usd": float(await session.scalar(paid) or 0),
        "pending_payouts": int(await session.scalar(pending) or 0),
    }


@router.get("/referrals/ledger")
async def referrals_ledger(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    referrer_user_id: int | None = None,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Referral commissions. ``q`` searches the referrer and the status."""
    stmt = select(ReferralLedger)
    count_stmt = select(func.count()).select_from(ReferralLedger)
    if since:
        stmt = stmt.where(ReferralLedger.created_at >= _parse_day(since))
        count_stmt = count_stmt.where(ReferralLedger.created_at >= _parse_day(since))
    if before:
        end = _parse_day(before) + timedelta(days=1)
        stmt = stmt.where(ReferralLedger.created_at < end)
        count_stmt = count_stmt.where(ReferralLedger.created_at < end)
    search = _search_condition(
        q,
        [
            ReferralLedger.status,
            _sub(User.tg_username, User.id == ReferralLedger.referrer_user_id),
            _sub(User.first_name, User.id == ReferralLedger.referrer_user_id),
            _sub(cast(User.tg_user_id, String), User.id == ReferralLedger.referrer_user_id),
            _sub(User.referral_code, User.id == ReferralLedger.referrer_user_id),
        ],
        number_columns=[_sub(User.tg_user_id, User.id == ReferralLedger.referrer_user_id)],
    )
    if search is not None:
        stmt = stmt.where(search)
        count_stmt = count_stmt.where(search)
    if status:
        stmt = stmt.where(ReferralLedger.status == status)
        count_stmt = count_stmt.where(ReferralLedger.status == status)
    if referrer_user_id:
        stmt = stmt.where(ReferralLedger.referrer_user_id == referrer_user_id)
        count_stmt = count_stmt.where(ReferralLedger.referrer_user_id == referrer_user_id)
    stmt = stmt.order_by(ReferralLedger.created_at.desc())

    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    referrer_ids = [entry.referrer_user_id for entry in rows]
    user_display_map = await _user_display_map(session, referrer_ids)
    # The search box has always accepted a referral code, but the table never showed one,
    # so an operator could type a code and had no way to tell whether the rows that came
    # back were the right ones. The column is the other half of that promise.
    code_map = await _referral_code_map(session, referrer_ids)
    return {
        "items": [
            {
                "id": str(entry.id),
                "referrer_user_id": str(entry.referrer_user_id),
                "referrer": user_display_map.get(entry.referrer_user_id, "—"),
                "referral_code": code_map.get(entry.referrer_user_id, "—"),
                "status": entry.status,
                "amount_usd": float(entry.amount_usd),
                "created_at": entry.created_at.isoformat(),
            }
            for entry in rows
        ],
        "total": total,
    }


def _payout_view(p: Payout, *, referrer_display: str) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "referrer": referrer_display,
        "amount_usd": float(p.amount_usd),
        "status": p.status,
        "requested_at": p.requested_at.isoformat(),
        "network": p.network,
        "wallet_address": p.wallet_address,
        "tx_hash": p.tx_hash,
    }


@router.get("/payouts/{payout_id}/instruction")
async def payout_instruction(
    payout_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Everything needed to send this payout by hand, with nothing to retype.

    The operator sends from our payout wallet; the watcher then spots that transfer
    on-chain and closes the payout itself with the real txid.
    """
    from app.services.payments.onchain.assets import find_spec
    from app.services.payouts import get_rail

    payout = await _get_payout(session, payout_id)
    rail = get_rail(payout.network)
    spec = find_spec(rail.asset, rail.network)
    amount = Decimal(str(payout.amount_usd))  # USDT — 1:1 with USD

    # EIP-681 opens MetaMask/Trust with the token, recipient and amount prefilled.
    # Tron wallets have no comparable standard, so the builder returns None there and the
    # UI shows a QR of the bare address — the operator still never retypes anything.
    # Shared builder so the chain id follows ONCHAIN_NETWORK: a hardcoded mainnet id would
    # make a scanned QR open the wallet on mainnet while we run on testnet.
    from app.services.payments.onchain.config import get_onchain_config
    from app.services.payments.onchain.payment_uri import build_payment_uri

    wallet_uri: str | None = None
    if spec is not None:
        try:
            onchain_network = get_onchain_config().network
        except Exception:
            onchain_network = "mainnet"
        wallet_uri = build_payment_uri(
            spec=spec,
            to_address=payout.wallet_address,
            amount=amount,
            network=onchain_network,
        )

    return {
        "payout_id": str(payout.id),
        "status": payout.status,
        "asset": rail.asset,
        "network": rail.network,
        "network_label": rail.label,
        "to_address": payout.wallet_address,
        "amount": str(amount),
        "token_contract": spec.token_contract if spec else None,
        "wallet_uri": wallet_uri,
        # QR payload: a wallet URI where one exists, otherwise the bare address
        "qr_payload": wallet_uri or payout.wallet_address,
        "auto_confirm": True,
        "hint": (
            "Отправьте точную сумму на этот адрес с платёжного кошелька. "
            "Статус выплаты обновится сам, когда транзакция появится в блокчейне."
        ),
    }


@router.get("/payouts")
async def list_payouts(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
) -> dict[str, Any]:
    """Open payouts by default — everything still awaiting action.

    Previously this defaulted to 'requested' only, which made an approved payout vanish
    from the queue before anyone could send it. 'Send' happens after approve, so both
    states have to stay visible.

    ``q`` searches the referrer, the status, and the payout's destination — the network,
    the wallet and the transaction hash — because "did we already send this one" is
    answered by pasting the hash, not by scrolling.
    """
    stmt = select(Payout).order_by(Payout.requested_at)
    if status:
        stmt = stmt.where(Payout.status == status)
    else:
        stmt = stmt.where(Payout.status.in_(("requested", "approved")))
    if since:
        stmt = stmt.where(Payout.requested_at >= _parse_day(since))
    if before:
        stmt = stmt.where(Payout.requested_at < _parse_day(before) + timedelta(days=1))
    search = _search_condition(
        q,
        [
            Payout.status,
            Payout.network,
            _sub(User.tg_username, User.id == Payout.referrer_user_id),
            _sub(User.first_name, User.id == Payout.referrer_user_id),
            _sub(cast(User.tg_user_id, String), User.id == Payout.referrer_user_id),
            # Same code the ledger below accepts. An operator who copies a code out of a
            # client's card is looking for that person's referral business, and their
            # payout requests are half of it.
            _sub(User.referral_code, User.id == Payout.referrer_user_id),
        ],
        number_columns=[_sub(User.tg_user_id, User.id == Payout.referrer_user_id)],
        # "Did we already send this one" is answered by pasting the hash or the address,
        # never by typing four digits out of either.
        opaque_columns=[Payout.wallet_address, func.coalesce(Payout.tx_hash, "")],
    )
    if search is not None:
        stmt = stmt.where(search)
    rows = (await session.execute(stmt)).scalars().all()
    user_display_map = await _user_display_map(session, [p.referrer_user_id for p in rows])
    items = [
        _payout_view(p, referrer_display=user_display_map.get(p.referrer_user_id, "—"))
        for p in rows
    ]
    return {"items": items, "total": len(items)}


async def _get_payout(session: DbSession, payout_id: int) -> Payout:
    payout = await session.get(Payout, payout_id)
    if payout is None:
        raise NotFound("payout not found")
    return payout


@router.post("/payouts/{payout_id}/approve")
async def approve_payout(
    payout_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Authorise a payout. The admin's Send button calls this, then shows the instructions.

    No ceiling here: the client never asked for one, and operators run this business
    without an owner in the loop. The step still earns its place — it is what the watcher
    requires before it will settle anything, it tells the partner their payout is coming,
    and it records who authorised it.
    """
    payout = await _get_payout(session, payout_id)
    if payout.status != "requested":
        raise Conflict("payout is not in 'requested' state")
    payout.status = "approved"
    payout.operator_id = admin.id
    payout.processed_at = _utcnow()
    await enqueue(
        session, user_id=payout.referrer_user_id, template_code="payout_approved",
        payload={"payout_id": payout.id, "amount_usd": float(payout.amount_usd)},
    )
    await audit.write(session, admin_id=admin.id, action="payout.approve", entity="payout",
                       entity_id=payout.id)
    referrer = await session.get(User, payout.referrer_user_id)
    return _payout_view(payout, referrer_display=_user_display(referrer))


class PayoutRejectBody(BaseModel):
    reason: str


@router.post("/payouts/{payout_id}/reject")
async def reject_payout(
    payout_id: int, body: PayoutRejectBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    payout = await _get_payout(session, payout_id)
    if payout.status != "requested":
        raise Conflict("payout is not in 'requested' state")
    payout.status = "rejected"
    payout.operator_id = admin.id
    payout.reject_reason = body.reason
    payout.processed_at = _utcnow()
    # release the ledger entries back to 'available' so the user can re-request
    ledger_rows = (
        (await session.execute(
            select(ReferralLedger).where(ReferralLedger.payout_id == payout.id)
        )).scalars().all()
    )
    for entry in ledger_rows:
        entry.status = "available"
        entry.payout_id = None
    await enqueue(
        session, user_id=payout.referrer_user_id, template_code="payout_rejected",
        payload={"payout_id": payout.id, "reason": body.reason},
    )
    await audit.write(session, admin_id=admin.id, action="payout.reject", entity="payout",
                       entity_id=payout.id, after={"reason": body.reason})
    referrer = await session.get(User, payout.referrer_user_id)
    return _payout_view(payout, referrer_display=_user_display(referrer))


class PayoutMarkPaidBody(BaseModel):
    tx_hash: str


@router.post("/payouts/{payout_id}/mark-paid")
async def mark_payout_paid(
    payout_id: int, body: PayoutMarkPaidBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    payout = await _get_payout(session, payout_id)
    if payout.status not in ("requested", "approved"):
        raise Conflict("payout must be requested or approved")
    payout.status = "paid"
    payout.operator_id = admin.id
    payout.tx_hash = body.tx_hash
    payout.processed_at = _utcnow()
    ledger_rows = (
        (await session.execute(
            select(ReferralLedger).where(ReferralLedger.payout_id == payout.id)
        )).scalars().all()
    )
    for entry in ledger_rows:
        entry.status = "paid"
    await enqueue(
        session, user_id=payout.referrer_user_id, template_code="payout_paid",
        payload={"payout_id": payout.id, "tx_hash": body.tx_hash},
    )
    await audit.write(session, admin_id=admin.id, action="payout.mark_paid", entity="payout",
                       entity_id=payout.id, after={"tx_hash": body.tx_hash})
    referrer = await session.get(User, payout.referrer_user_id)
    return _payout_view(payout, referrer_display=_user_display(referrer))


@router.get("/settings/referral")
async def get_referral_settings(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    return {
        # default must match services/referral.accrue's fallback, or the screen would show
        # one number while accruals used another
        "referral_pct": await settings_svc.get(session, "referral_pct", 20),
        "referral_hold_days": await settings_svc.get(session, "referral_hold_days", 14),
        "referral_min_payout_usd": await settings_svc.get(session, "referral_min_payout_usd", 20),
    }


class ReferralSettingsPatch(BaseModel):
    # Reject unknown keys instead of ignoring them: a client sending the wrong field names
    # used to get a 200 with nothing saved, which is how the admin form silently broke.
    model_config = ConfigDict(extra="forbid")

    referral_pct: float | None = Field(default=None, ge=0, le=100)
    referral_hold_days: int | None = Field(default=None, ge=0, le=365)
    referral_min_payout_usd: float | None = Field(default=None, ge=0)


@router.patch("/settings/referral")
async def patch_referral_settings(
    body: ReferralSettingsPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    # Operator-editable, same tier as tariff pricing — the referral percentage is a
    # day-to-day commercial dial, not an ownership-level setting.
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        await settings_svc.set_value(session, key, value, admin_id=admin.id)
    await audit.write(session, admin_id=admin.id, action="settings.referral.update",
                       entity="app_setting", entity_id="referral", after=updates)
    return await get_referral_settings(admin, session)


# ── broadcasts ───────────────────────────────────────────────────────────
def _broadcast_view(b: Broadcast) -> dict[str, Any]:
    # sent_at prefers the completion timestamp (finished_at); while still in-flight
    # (status='sending') falls back to started_at so the admin sees *something*.
    sent_at = b.finished_at or b.started_at
    return {
        "id": str(b.id),
        "title": b.title,
        "body": b.body,
        "audience_filter": b.audience_filter,
        "status": b.status,
        "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
        "sent_at": sent_at.isoformat() if sent_at else None,
    }


@router.get("/broadcasts")
async def list_broadcasts(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    rows = (
        await session.execute(select(Broadcast).order_by(Broadcast.created_at.desc()))
    ).scalars().all()
    items = [_broadcast_view(b) for b in rows]
    return {"items": items, "total": len(items)}


class BroadcastBody(BaseModel):
    title: str
    body: str
    audience_filter: dict[str, Any] = {}


@router.post("/broadcasts", status_code=201)
async def create_broadcast(
    body: BroadcastBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    broadcast = Broadcast(
        title=body.title, body=body.body, audience_filter=body.audience_filter,
        created_by=admin.id,
    )
    session.add(broadcast)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="broadcast.create", entity="broadcast",
                       entity_id=broadcast.id)
    return _broadcast_view(broadcast)


async def _get_broadcast(session: DbSession, broadcast_id: int) -> Broadcast:
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise NotFound("broadcast not found")
    return broadcast


class BroadcastPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    audience_filter: dict[str, Any] | None = None


@router.patch("/broadcasts/{broadcast_id}")
async def patch_broadcast(
    broadcast_id: int, body: BroadcastPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    broadcast = await _get_broadcast(session, broadcast_id)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(broadcast, field, value)
    await audit.write(session, admin_id=admin.id, action="broadcast.update", entity="broadcast",
                       entity_id=broadcast.id, after=updates)
    return _broadcast_view(broadcast)


class ScheduleBody(BaseModel):
    scheduled_at: datetime


@router.post("/broadcasts/{broadcast_id}/schedule")
async def schedule_broadcast(
    broadcast_id: int, body: ScheduleBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    broadcast = await _get_broadcast(session, broadcast_id)
    broadcast.status = "scheduled"
    broadcast.scheduled_at = body.scheduled_at
    await audit.write(session, admin_id=admin.id, action="broadcast.schedule", entity="broadcast",
                       entity_id=broadcast.id, after={"scheduled_at": body.scheduled_at.isoformat()})
    return _broadcast_view(broadcast)


@router.post("/broadcasts/{broadcast_id}/send-now")
async def send_now_broadcast(
    broadcast_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    broadcast = await _get_broadcast(session, broadcast_id)
    # Build the recipient list now so the worker's "sending" pass has deliveries to send;
    # without this a send-now broadcast has 0 recipients and instantly marks itself done.
    await content.materialize_broadcast(session, broadcast)
    broadcast.status = "sending"
    broadcast.started_at = _utcnow()
    await audit.write(session, admin_id=admin.id, action="broadcast.send_now", entity="broadcast",
                       entity_id=broadcast.id)
    return _broadcast_view(broadcast)


@router.get("/broadcasts/{broadcast_id}/progress")
async def broadcast_progress(
    broadcast_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    broadcast = await _get_broadcast(session, broadcast_id)
    return {
        "total": broadcast.total_count,
        "delivered": broadcast.sent_count,
        "failed": broadcast.failed_count,
        "status": broadcast.status,
    }


# ── publications (channels / posts) ─────────────────────────────────────
def _channel_view(c: Channel) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "name": c.title,
        "handle": c.username,
        "is_active": c.is_active,
    }


@router.get("/channels")
async def list_channels(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Channel).order_by(Channel.title))).scalars().all()
    return [_channel_view(c) for c in rows]


class ChannelBody(BaseModel):
    tg_chat_id: int
    title: str
    username: str | None = None


@router.post("/channels", status_code=201)
async def create_channel(
    body: ChannelBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    existing = await session.scalar(select(Channel.id).where(Channel.tg_chat_id == body.tg_chat_id))
    if existing is not None:
        raise Conflict("channel already registered")
    channel = Channel(tg_chat_id=body.tg_chat_id, title=body.title, username=body.username)
    session.add(channel)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="channel.create", entity="channel",
                       entity_id=channel.id)
    return _channel_view(channel)


class ChannelPatch(BaseModel):
    title: str | None = None
    username: str | None = None
    is_active: bool | None = None


@router.patch("/channels/{channel_id}")
async def patch_channel(
    channel_id: int, body: ChannelPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    channel = await session.get(Channel, channel_id)
    if channel is None:
        raise NotFound("channel not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(channel, field, value)
    await audit.write(session, admin_id=admin.id, action="channel.update", entity="channel",
                       entity_id=channel.id, after=updates)
    return _channel_view(channel)


def _post_view(p: Post) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "channel_id": str(p.channel_id),
        "title": p.title,
        "body": p.body,
        "status": p.status,
        "published_at": p.posted_at.isoformat() if p.posted_at else None,
        "views": 0,
        "clicks": p.clicks,
    }


@router.get("/posts")
async def list_posts(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    rows = (await session.execute(select(Post).order_by(Post.created_at.desc()))).scalars().all()
    items = [_post_view(p) for p in rows]
    return {"items": items, "total": len(items)}


class PostBody(BaseModel):
    channel_id: int
    title: str
    body: str
    deep_link_code: str | None = None
    scheduled_at: datetime | None = None


@router.post("/posts", status_code=201)
async def create_post(body: PostBody, admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    code = body.deep_link_code or secrets.token_hex(4)
    post = Post(
        channel_id=body.channel_id, title=body.title, body=body.body, deep_link_code=code,
        scheduled_at=body.scheduled_at, created_by=admin.id,
    )
    session.add(post)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="post.create", entity="post",
                       entity_id=post.id)
    return _post_view(post)


async def _get_post(session: DbSession, post_id: int) -> Post:
    post = await session.get(Post, post_id)
    if post is None:
        raise NotFound("post not found")
    return post


class PostPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    scheduled_at: datetime | None = None


@router.patch("/posts/{post_id}")
async def patch_post(
    post_id: int, body: PostPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    post = await _get_post(session, post_id)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(post, field, value)
    await audit.write(session, admin_id=admin.id, action="post.update", entity="post",
                       entity_id=post.id, after=updates)
    return _post_view(post)


@router.post("/posts/{post_id}/publish")
async def publish_post(post_id: int, admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    post = await _get_post(session, post_id)
    post.status = "scheduled"
    # Stamp a due time so publish_scheduled_posts picks it up (its query requires
    # scheduled_at <= now); keep an existing future schedule if one was set.
    post.scheduled_at = post.scheduled_at or _utcnow()
    await audit.write(session, admin_id=admin.id, action="post.publish", entity="post",
                       entity_id=post.id)
    return _post_view(post)


@router.get("/posts/{post_id}/attribution")
async def post_attribution(
    post_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    post = await _get_post(session, post_id)
    signups = int(
        await session.scalar(
            select(func.count()).select_from(User).where(User.source_post_id == post.id)
        )
        or 0
    )
    orders_count = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.source_post_id == post.id)
        )
        or 0
    )
    revenue = float(
        await session.scalar(
            select(func.coalesce(func.sum(Order.amount_usd), 0)).where(
                Order.source_post_id == post.id, Order.status == "completed"
            )
        )
        or 0
    )
    return {
        "clicks": post.clicks,
        "signups": signups,
        "orders_count": orders_count,
        "revenue": revenue,
    }


# ── faq ──────────────────────────────────────────────────────────────────
def _faq_view(f: FaqItem) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "question": f.question,
        "answer": f.answer,
        "is_published": f.is_active,
    }


@router.get("/faq")
async def list_admin_faq(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(FaqItem).order_by(FaqItem.sort_order))
    ).scalars().all()
    return [_faq_view(f) for f in rows]


class FaqBody(BaseModel):
    category: str = "general"
    question: str
    answer: str
    sort_order: int = 100
    is_active: bool = True


@router.post("/faq", status_code=201)
async def create_faq(body: FaqBody, admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    faq = FaqItem(**body.model_dump(), updated_by=admin.id)
    session.add(faq)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="faq.create", entity="faq_item",
                       entity_id=faq.id)
    return _faq_view(faq)


async def _get_faq(session: DbSession, faq_id: int) -> FaqItem:
    faq = await session.get(FaqItem, faq_id)
    if faq is None:
        raise NotFound("faq item not found")
    return faq


class FaqPatch(BaseModel):
    category: str | None = None
    question: str | None = None
    answer: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


@router.patch("/faq/{faq_id}")
async def patch_faq(
    faq_id: int, body: FaqPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    faq = await _get_faq(session, faq_id)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(faq, field, value)
    faq.updated_by = admin.id
    await audit.write(session, admin_id=admin.id, action="faq.update", entity="faq_item",
                       entity_id=faq.id, after=updates)
    return _faq_view(faq)


@router.delete("/faq/{faq_id}")
async def delete_faq(faq_id: int, admin: CurrentAdmin, session: DbSession) -> dict[str, bool]:
    faq = await _get_faq(session, faq_id)
    await session.delete(faq)
    await audit.write(session, admin_id=admin.id, action="faq.delete", entity="faq_item",
                       entity_id=faq_id)
    return {"deleted": True}


# ── notifications ────────────────────────────────────────────────────────
@router.get("/notifications/log")
async def notifications_log(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(NotificationOutbox)
    count_stmt = select(func.count()).select_from(NotificationOutbox)
    if status:
        stmt = stmt.where(NotificationOutbox.status == status)
        count_stmt = count_stmt.where(NotificationOutbox.status == status)
    if user_id:
        stmt = stmt.where(NotificationOutbox.user_id == user_id)
        count_stmt = count_stmt.where(NotificationOutbox.user_id == user_id)
    stmt = stmt.order_by(NotificationOutbox.scheduled_at.desc())

    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    user_display_map = await _user_display_map(session, [n.user_id for n in rows])
    return {
        "items": [
            {
                "id": str(n.id),
                "user": user_display_map.get(n.user_id, "—"),
                "type": n.template_code,
                "status": n.status,
                "created_at": n.scheduled_at.isoformat(),
            }
            for n in rows
        ],
        "total": total,
    }


@router.get("/notifications/settings")
async def get_notification_settings(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    from app.bot.notifier import DEFAULT_TEXTS
    from app.services.notifications import TEMPLATES

    texts = {}
    for code in TEMPLATES:
        override = await settings_svc.get(session, f"notify_texts:{code}", "")
        # Return the EFFECTIVE text the client currently receives: the operator's
        # override if set, otherwise the built-in default — so the admin sees the
        # actual message each template sends, not a blank box.
        texts[code] = override if override else DEFAULT_TEXTS.get(code, "")
    return texts


class NotificationSettingsPatch(BaseModel):
    texts: dict[str, str]


@router.patch("/notifications/settings")
async def patch_notification_settings(
    body: NotificationSettingsPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    for code, text_val in body.texts.items():
        await settings_svc.set_value(session, f"notify_texts:{code}", text_val, admin_id=admin.id)
    await audit.write(session, admin_id=admin.id, action="notifications.settings.update",
                       entity="app_setting", entity_id="notify_texts", after=body.texts)
    return await get_notification_settings(admin, session)


# ── receiving wallets ────────────────────────────────────────────────────
async def _payment_rails_view(session: DbSession) -> dict[str, Any]:
    """Every rail the watcher has an engine for, with whatever address it holds.

    One list, not two. A separate "supported but not configured" section made the main
    list read as "the coins we accept" while it actually showed "the coins someone
    configured" — and an operator who wants to start taking Litecoin should not have to
    work out that the way to do it is somewhere other than the row that says Litecoin.
    A rail with no address is simply not offered at checkout.
    """
    from app.core.config import settings
    from app.services.payments.onchain.assets import SPECS, get_spec
    from app.services.payments.onchain.config import (
        DEFAULT_CONFIRMATIONS,
        OnchainConfigError,
        get_onchain_config,
        rails_are_console_managed,
    )
    from app.services.payments.onchain.rails import refresh_rails, supported_rails
    from app.services.payouts import PAYOUT_RAILS

    await refresh_rails(session)

    error: str | None = None
    try:
        cfg = get_onchain_config()
    except OnchainConfigError as exc:
        cfg = None
        error = str(exc)

    rails: list[dict[str, Any]] = []
    for asset, network, chain in supported_rails():
        method = cfg.method(asset, network) if cfg else None
        spec = method.spec if method else get_spec(asset, network)
        rails.append(
            {
                "asset": asset,
                "network": network,
                "chain": chain,
                "address": method.address if method else "",
                "confirmations": (
                    method.confirmations if method else DEFAULT_CONFIRMATIONS.get(chain, 12)
                ),
                "token_contract": spec.token_contract or spec.token_mint,
                "is_stablecoin": spec.is_stable,
            }
        )

    # The other half of the money flow: the wallets we SEND referral payouts from. They
    # are not where anything is received — they are watched so a payout an operator sends
    # by hand gets its real transaction hash attached instead of being typed in. Three
    # rails, fixed by the client's decision that payouts are USDT only.
    sent_from = {s.network: s.address for s in (cfg.payout_sources if cfg else ())}
    payout_wallets = [
        {
            "network": rail.network,
            "chain": rail.chain,
            "asset": rail.asset,
            "label": rail.label,
            "address": sent_from.get(rail.network, ""),
        }
        for rail in PAYOUT_RAILS.values()
    ]

    return {
        "provider": settings.payment_provider,
        "network": cfg.network if cfg else settings.onchain_network,
        "payout_wallets": payout_wallets,
        # The rails are inert unless the provider is actually the on-chain one — worth
        # saying on the page, or the addresses read as live when nothing is watching them.
        "watching": settings.payment_provider == "onchain",
        # False means these addresses still come from ONCHAIN_METHODS in the deploy
        # environment and the first save here takes over from it — worth showing, because
        # otherwise nobody can tell which of the two is actually in charge.
        "console_managed": rails_are_console_managed(),
        "supported_count": len(SPECS),
        "rails": rails,
        "error": error,
    }


@router.get("/payment-rails")
async def list_payment_rails(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    return await _payment_rails_view(session)


class PaymentRailsBody(BaseModel):
    rails: list[dict[str, Any]]
    payout_wallets: list[dict[str, Any]] | None = None


@router.put("/payment-rails")
async def put_payment_rails(
    body: PaymentRailsBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Replace the rail list — the addresses customer payments are sent to.

    This is the most consequential write in the console: from the moment it lands, every
    invoice quotes the new address, and money sent to the old one arrives somewhere the
    watcher is no longer looking. Three things stand behind it.

    Addresses are format-checked against the chain and the network they are being set on.
    That catches the mistake people actually make — a Tron address pasted onto the
    Ethereum rail, or a mainnet address while the deployment is on testnet. It is not a
    checksum: two transposed characters in the middle still pass, so the address has to be
    read back against the wallet before real money is pointed at it.

    The change is audit-logged rail by rail, with the address that was there before, so
    "when did this address change and who changed it" has an answer.

    And nothing here can spend: the backend holds no key on any chain. A wrong address
    means money lands where we do not watch, not that money leaves.
    """
    from app.services.payments.onchain.config import OnchainConfigError, get_onchain_config
    from app.services.payments.onchain.rails import save_payout_wallets, save_rails

    before = {
        (m.asset, m.network): m.address
        for m in (get_onchain_config().enabled_methods() if _config_ok() else [])
    }
    before_payout = {s.network: s.address for s in (
        get_onchain_config().payout_sources if _config_ok() else ()
    )}
    try:
        saved = await save_rails(
            session, body.rails, admin_id=admin.id, network=_onchain_network()
        )
        saved_payout = (
            await save_payout_wallets(session, body.payout_wallets, admin_id=admin.id)
            if body.payout_wallets is not None
            else None
        )
    except OnchainConfigError as exc:
        raise ValidationError(str(exc)) from None

    after = {(r["asset"], r["network"]): r["address"] for r in saved}
    changes = {
        f"{asset}/{network}": {"from": before.get((asset, network), ""), "to": address}
        for (asset, network), address in after.items()
        if before.get((asset, network), "") != address
    }
    for (asset, network), address in before.items():
        if (asset, network) not in after:
            changes[f"{asset}/{network}"] = {"from": address, "to": ""}
    if saved_payout is not None:
        after_payout = {w["network"]: w["address"] for w in saved_payout}
        for network in set(before_payout) | set(after_payout):
            was, now = before_payout.get(network, ""), after_payout.get(network, "")
            if was != now:
                changes[f"payout:{network}"] = {"from": was, "to": now}

    await audit.write(
        session, admin_id=admin.id, action="payment_rails.update", entity="app_setting",
        entity_id="onchain_rails", after=changes,
    )
    return await _payment_rails_view(session)


def _config_ok() -> bool:
    from app.services.payments.onchain.config import OnchainConfigError, get_onchain_config

    try:
        get_onchain_config()
    except OnchainConfigError:
        return False
    return True


def _onchain_network() -> str:
    from app.core.config import settings

    return settings.onchain_network


# ── system ───────────────────────────────────────────────────────────────
@router.get("/settings")
async def get_all_settings(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    return {row.key: row.value for row in rows}


class SettingsPatch(BaseModel):
    values: dict[str, Any]


# Allowlist for the bulk PATCH /settings endpoint. Keys with their own dedicated
# endpoint ('tos', 'notify_texts:*') are excluded to prevent accidental clobbering.
_SETTINGS_WHITELIST: frozenset[str] = frozenset(
    {
        "referral_pct",
        "referral_hold_days",
        "referral_min_payout_usd",
        "invoice_ttl_minutes",
        "rotation_cooldown_sec",
        "pool_low_watermark",
        "pool_check_interval_minutes",
        "pool_alert_repeat_hours",
        "ops_alert_chats",
        "attribution",
        "bot_channel_url",
        "bot_support_url",
        # AI support assistant — two operator toggles plus the single chat its courtesy
        # copies go to (see services/ai_support.py). The chat is editable through the API
        # but deliberately not on screen: it defaults to the support handle, and the panel
        # offers the two decisions an operator actually makes.
        "ai_assistant_enabled",
        "ai_assistant_ping_ops",
        "ai_assistant_ping_chat",
    }
)


@router.patch("/settings")
async def patch_all_settings(
    body: SettingsPatch, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    rejected = [k for k in body.values if k not in _SETTINGS_WHITELIST]
    if rejected:
        raise ValidationError(
            f"unknown settings keys (use the dedicated endpoint): {', '.join(sorted(rejected))}"
        )
    for key, value in body.values.items():
        await settings_svc.set_value(session, key, value, admin_id=admin.id)
    await audit.write(session, admin_id=admin.id, action="settings.update", entity="app_setting",
                       entity_id="bulk", after=body.values)
    return await get_all_settings(admin, session)


# ── welcome image (bot /start greeting photo) ──────────────────────────────
# Not part of the key/value bag above: an image doesn't fit a JSONB settings value, and the
# generic settings grid renders every value as a text input. See app/services/media.py for
# where the bytes actually live (Postgres, not the settings table — Railway's disk doesn't
# survive a deploy) and for why a successful upload always clears the cached Telegram
# file_id (bot/handlers/start.py resends by that id; a stale one would keep the old photo
# going out on every /start).
@router.post("/settings/welcome-image")
async def upload_welcome_image(
    admin: CurrentAdmin, session: DbSession, file: UploadFile = File(...)
) -> dict[str, Any]:
    data = await file.read()
    if len(data) > media.MAX_WELCOME_IMAGE_BYTES:
        limit_mb = media.MAX_WELCOME_IMAGE_BYTES / (1024 * 1024)
        raise ValidationError(f"image is too large — {limit_mb:.0f} MB max")

    # The real type, off the file's own bytes — file.content_type is just whatever the
    # client claimed in the multipart part and is not trustworthy on its own.
    content_type = media.sniff_image_content_type(data)
    if content_type is None:
        raise ValidationError("unsupported image type — use JPEG, PNG, or WebP")

    await media.set_welcome_image(
        session, content_type=content_type, data=data, admin_id=admin.id
    )
    await audit.write(
        session, admin_id=admin.id, action="settings.welcome_image_update",
        entity="app_setting", entity_id="welcome_image",
        after={"content_type": content_type, "size_bytes": len(data)},
    )
    return {
        "content_type": content_type,
        "size_bytes": len(data),
        "updated_at": _utcnow().isoformat(),
    }


@router.get("/settings/welcome-image")
async def get_welcome_image_admin(admin: CurrentAdmin, session: DbSession) -> Response:
    asset = await media.get_welcome_image(session)
    # no-store: the admin preview appends its own cache-busting query param after an
    # upload, but this belt-and-suspenders header is what stops an intermediary (proxy,
    # browser heuristic cache) from ever answering out of a cached copy on its own.
    return Response(
        content=asset.data,
        media_type=asset.content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/terms")
async def get_terms_admin(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    tos = await settings_svc.get(session, "tos", {})
    return {
        "version": tos.get("version"),
        "text_md": tos.get("text_md", ""),
        "questions": tos.get("questions", []),
    }


class TermsBody(BaseModel):
    text_md: str
    questions: list[dict[str, Any]] = []
    publish: bool = False


@router.put("/terms")
async def put_terms(body: TermsBody, admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    """Write the terms. Publishing bumps the version; saving does not.

    The version is the gate: `is_tos_accepted` compares it against what each client has
    accepted, so bumping it puts every customer back in front of the acceptance screen
    before they can use the app. That is right for a change of substance and wrong for a
    typo, and until now every write bumped it — there was no way to fix a word without
    re-prompting the entire user base.

    A first write always takes version 1: version 0 means "no terms configured", which
    turns the gate off entirely.
    """
    tos = await settings_svc.get(session, "tos", {})
    current = int(tos.get("version") or 0)
    version = current + 1 if body.publish or not current else current
    new_tos = {"version": version, "text_md": body.text_md, "questions": body.questions}
    await settings_svc.set_value(session, "tos", new_tos, admin_id=admin.id)
    await audit.write(session, admin_id=admin.id, action="terms.update", entity="app_setting",
                       entity_id="tos", after={"version": version, "published": body.publish})
    return new_tos


def _admin_user_view(a: AdminUser) -> dict[str, Any]:
    return {
        "id": a.id,
        "email": a.email,
        "display_name": a.display_name,
        "role": a.role,
        "is_active": a.is_active,
        "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        "created_at": a.created_at.isoformat(),
        "telegram_username": a.telegram_username,
        # The console shows the handle either way; this says whether a code can actually be
        # delivered yet, which is only true once that person has opened the bot.
        "telegram_linked": a.telegram_user_id is not None,
    }


async def _set_handle(session: AsyncSession, target: AdminUser, raw: str | None) -> str | None:
    """Write a handle onto an account, dropping any binding that belonged to the old one."""
    try:
        handle = admin_telegram.normalise_handle(raw)
    except admin_telegram.InvalidHandle as exc:
        raise ValidationError(str(exc)) from exc
    if handle is not None:
        clash = await admin_telegram.handle_taken_by(session, handle, excluding=target.id)
        if clash is not None:
            raise Conflict("another account already uses this Telegram handle")
    if handle != target.telegram_username:
        # A different handle means a different person: their codes must stop going to the
        # inbox the old handle was bound to. The new one binds on their first Start.
        target.telegram_user_id = None
    target.telegram_username = handle
    return handle


@router.get("/admins")
async def list_admins(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    # Deleted accounts stay in the table so old audit entries can still name them, and are
    # not accounts any more — so they do not belong on the list of accounts.
    rows = (
        await session.execute(
            select(AdminUser)
            .where(AdminUser.deleted_at.is_(None))
            .order_by(AdminUser.created_at)
        )
    ).scalars().all()
    return [_admin_user_view(a) for a in rows]


# The console asks for at least this much; the API has to agree, or the rule is a
# suggestion that any direct request ignores.
MIN_PASSWORD_LENGTH = 10


class AdminCreateBody(BaseModel):
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    display_name: str
    telegram_username: str | None = None


@router.post("/admins", status_code=201)
async def create_admin(
    body: AdminCreateBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    existing = await session.scalar(select(AdminUser.id).where(AdminUser.email == body.email))
    if existing is not None:
        raise Conflict("admin with this email already exists")
    # No role: every admin has the same rights. The column keeps its 'operator' default so
    # bringing tiers back later is a code change, not a migration.
    new_admin = AdminUser(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(new_admin)
    await session.flush()
    handle = await _set_handle(session, new_admin, body.telegram_username)
    await audit.write(session, admin_id=admin.id, action="admin.create", entity="admin_user",
                       entity_id=new_admin.id,
                       after={"email": body.email, "telegram_username": handle})
    return _admin_user_view(new_admin)


class AdminPatchBody(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)
    telegram_username: str | None = None


@router.patch("/admins/{admin_id}")
async def patch_admin(
    admin_id: int, body: AdminPatchBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    target = await session.get(AdminUser, admin_id)
    if target is None:
        raise NotFound("admin not found")
    # The one guard worth keeping: deactivating yourself signs you out of the console with
    # no way back in. Nothing to do with tiers — it is true of the last admin standing.
    if admin.id == admin_id and body.is_active is False:
        raise Conflict("cannot deactivate yourself")
    updates = body.model_dump(exclude_unset=True, exclude={"password", "telegram_username"})
    for field, value in updates.items():
        setattr(target, field, value)
    if "telegram_username" in body.model_fields_set:
        updates["telegram_username"] = await _set_handle(session, target, body.telegram_username)
    if body.password is not None:
        target.password_hash = hash_password(body.password)
        updates["password"] = "***"  # noqa: S105  redaction marker, not a real secret

    # Changing a password or switching an account off has to end the sessions that account
    # already holds, not merely the next login. The refresh cookie lives 14 days and
    # rotates itself, so before this an operator who had left kept a working console —
    # one that can move where customer payments are received — for a fortnight after
    # their password was changed. Applies to your own account too: you will be signed out
    # and sign back in with the new password, which is the honest reading of "changed".
    if body.password is not None or body.is_active is False:
        # Full precision, compared against the token's own millisecond stamp. At second
        # resolution this had to choose between keeping a revoked session alive and
        # refusing a legitimate login made in the same second — the full suite caught
        # both, one after the other. Measuring finely removes the choice.
        target.sessions_valid_from = _utcnow()
        updates["sessions_ended"] = True
    await audit.write(session, admin_id=admin.id, action="admin.update", entity="admin_user",
                       entity_id=target.id, after=updates)
    return _admin_user_view(target)


@router.delete("/admins/{admin_id}", status_code=200)
async def delete_admin(
    admin_id: int, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    """Delete an account: gone from the list, cannot sign in, email and handle released.

    The row itself stays, and that is the whole design rather than a shortcut. Three screens
    print an admin's name from this table — the audit log, the client conversation, and
    publication comments — so dropping the row turns "who revoked this access" into "—" at
    the exact moment somebody is asking. Keeping the name is the point; keeping the account
    is not, so everything that makes it an account is taken away:

    * the password is replaced with a value nothing can match, so the old one is dead;
    * the email is stamped `deleted-{id}-…` and the Telegram handle cleared, which frees
      both for the replacement person — recreating an account with the same address is the
      usual next step after deleting one made by mistake;
    * `is_active` goes false and `sessions_valid_from` moves to now, which ends any session
      the account is holding this second rather than at cookie expiry;
    * `deleted_at` hides it from the list.
    """
    target = await session.get(AdminUser, admin_id)
    if target is None or target.deleted_at is not None:
        raise NotFound("admin not found")
    if target.id == admin.id:
        # Signing yourself out permanently, with no way back in, is never the intent.
        raise Conflict("cannot delete the account you are signed in with")

    view = _admin_user_view(target)
    now = _utcnow()
    target.deleted_at = now
    target.is_active = False
    target.sessions_valid_from = now
    # Not a hash of anything: `hash_password(token_urlsafe())` would still be a hash of a
    # password that exists somewhere for an instant. This one matches nothing, ever.
    target.password_hash = "deleted"  # noqa: S105  a value no verifier can accept
    target.email = f"deleted-{target.id}-{target.email}"
    target.telegram_username = None
    target.telegram_user_id = None

    await audit.write(session, admin_id=admin.id, action="admin.delete", entity="admin_user",
                       entity_id=target.id,
                       before={"email": view["email"], "display_name": view["display_name"]})
    return {"deleted": True, "admin": view}


@router.get("/audit")
async def list_audit(
    admin: CurrentAdmin,
    session: DbSession,
    q: str | None = None,
    since: str | None = None,
    before: str | None = None,
    entity: str | None = None,
    admin_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """The trail of who did what, searchable by any of it except the timestamp.

    ``q`` runs over the admin, the entity and the action at once; the date is a range
    instead, because nobody searches for a timestamp by typing it. The old screen had a
    box per column, and the one labelled "admin" sent `?admin=` while this signature has
    only `admin_id` — it silently filtered nothing at all.
    """
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
        count_stmt = count_stmt.where(AuditLog.entity == entity)
    if admin_id:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
        count_stmt = count_stmt.where(AuditLog.admin_id == admin_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= _parse_day(since))
        count_stmt = count_stmt.where(AuditLog.created_at >= _parse_day(since))
    if before:
        # inclusive end-of-day, same as the payments ledger
        end = _parse_day(before) + timedelta(days=1)
        stmt = stmt.where(AuditLog.created_at < end)
        count_stmt = count_stmt.where(AuditLog.created_at < end)
    # The admin is shown by display name, so it has to be searchable by display name —
    # matching only the numeric id would mean searching for what the screen never shows.
    admin_name = func.coalesce(
        select(AdminUser.display_name)
        .where(AdminUser.id == AuditLog.admin_id)
        .scalar_subquery(),
        "",
    )
    search = _search_condition(
        q, [AuditLog.entity, AuditLog.action, cast(AuditLog.entity_id, String), admin_name]
    )
    if search is not None:
        stmt = stmt.where(search)
        count_stmt = count_stmt.where(search)
    stmt = stmt.order_by(AuditLog.created_at.desc())

    limit, offset = _page(limit, offset)
    total = int(await session.scalar(count_stmt) or 0)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    admin_display_map = await _admin_display_map(session, [a.admin_id for a in rows])
    return {
        "items": [
            {
                "id": str(a.id),
                "admin": admin_display_map.get(a.admin_id, "—"),
                "entity": a.entity,
                "action": a.action,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
        "total": total,
    }
