"""Admin domain API: dashboard, clients, tariffs, pool, accesses, orders, requests,
referrals, broadcasts, publications, faq, notifications, system settings.

Stage 2 scope: iproxy sync/broadcast-send/post-publish are stubbed (Stage 3/4 workers
own the real dispatch); everything else is fully wired against the real tables.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdmin, DbSession, Owner
from app.core.errors import Conflict, NotFound, ValidationError
from app.core.security import hash_password
from app.models import (
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
    Order,
    PaymentEvent,
    Payout,
    Post,
    ReferralLedger,
    Refund,
    Request,
    RequestComment,
    Tariff,
    TosAcceptance,
    User,
)
from app.models.access import Access
from app.services import audit, referral
from app.services import settings as settings_svc
from app.services.notifications import enqueue
from app.services.provisioning import allocator
from app.services.provisioning.lifecycle import (
    extend_access,
    provision_access,
    revoke_access,
    rotate_ip,
    swap_access,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

_ACTIVE_ACCESS = ("provisioning", "active", "expiring")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)


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
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q:
        like = f"%{q}%"
        cond = or_(
            User.tg_username.ilike(like), User.first_name.ilike(like), User.email.ilike(like)
        )
        if q.isdigit():  # tg_id search: exact numeric match, ORed into the text search
            cond = or_(cond, User.tg_user_id == int(q))
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
    # Two bulk queries replace the per-client N+1 (total_spent + active_count).
    # Kept separate to avoid a cartesian-product inflation between orders and accesses.
    spent_by_user: dict[int, float] = {}
    active_by_user: dict[int, int] = {}
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
    conn_lookup: dict[int, tuple[str | None, str | None]] = {}
    if conn_ids:
        conn_rows = (
            await session.execute(
                select(Connection.id, Location.city, Connection.carrier)
                .outerjoin(Location, Location.id == Connection.location_id)
                .where(Connection.id.in_(conn_ids))
            )
        ).all()
        for cid, city, carrier in conn_rows:
            conn_lookup[cid] = (city, carrier)

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
                "city": conn_lookup.get(a.connection_id, (None, None))[0],
                "carrier": conn_lookup.get(a.connection_id, (None, None))[1],
                "ip": None,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in accesses
        ],
        "orders": [
            {
                "id": str(o.public_id),
                "status": o.status,
                "provider": provider_by_order.get(o.id),
                "amount_usd": float(o.amount_usd),
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ],
        "referral": {
            "code": user.referral_code,
            "clicks": 0,
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
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(Connection)
    count_stmt = select(func.count()).select_from(Connection)
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
    from app.services.provisioning.sync import sync_pool

    if not settings.feature_real_provisioning:
        return {"synced": False, "detail": "real provisioning disabled (mock mode)"}
    result = await sync_pool(session)
    await audit.write(
        session, admin_id=admin.id, action="connection.sync", entity="pool",
        entity_id="iproxy", after=result,
    )
    return {"synced": True, **result}


@router.get("/pool/summary")
async def pool_summary(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
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
                      AND NOT EXISTS (
                        SELECT 1 FROM accesses a
                        WHERE a.connection_id = c.id
                          AND a.status IN ('provisioning','active','expiring'))
                ) AS free,
                count(*) FILTER (
                    WHERE c.online_status = 'online'
                      AND EXISTS (
                        SELECT 1 FROM accesses a
                        WHERE a.connection_id = c.id
                          AND a.status IN ('provisioning','active','expiring'))
                ) AS busy,
                count(*) FILTER (WHERE c.online_status = 'offline') AS offline
            FROM connections c
            LEFT JOIN locations l ON l.id = c.location_id
            GROUP BY l.city, l.state_code, c.carrier
            ORDER BY l.city NULLS LAST, c.carrier NULLS LAST
            """
        )
    )
    cities: list[dict[str, Any]] = []
    slots_total = slots_used = slots_free = 0
    for city, state, carrier, total, free, busy, offline in rows:
        total, free, busy, offline = int(total), int(free), int(busy), int(offline)
        slots_total += total
        slots_used += busy
        slots_free += free
        cities.append(
            {
                "city": city,
                "state": state,
                "carrier": carrier,
                "slots_total": total,
                "slots_used": busy,
                "online_nodes": free + busy,
                "offline_nodes": offline,
                "full_nodes": busy,
            }
        )
    return {
        "slots_total": slots_total,
        "slots_used": slots_used,
        "slots_free": slots_free,
        "cities": cities,
    }


# ── accesses (packages) ─────────────────────────────────────────────────
def _access_view(
    a: Access, *, user_display: str, city: str | None, carrier: str | None
) -> dict[str, Any]:
    return {
        "id": str(a.public_id),
        "user": user_display,
        "status": a.status,
        "city": city,
        "carrier": carrier,
        "ip": None,
        "tariff_code": a.tariff_code,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "created_at": a.created_at.isoformat(),
    }


async def _access_extras(session: DbSession, a: Access) -> tuple[str, str | None, str | None]:
    """Resolve (user_display, city, carrier) for a single access row (used by the
    single-object mutation endpoints below; list_admin_accesses bulk-joins instead)."""
    user = await session.get(User, a.user_id)
    conn = await session.get(Connection, a.connection_id)
    city: str | None = None
    carrier = conn.carrier if conn else None
    if conn is not None and conn.location_id is not None:
        loc = await session.get(Location, conn.location_id)
        city = loc.city if loc else None
    return _user_display(user), city, carrier


@router.get("/accesses")
async def list_admin_accesses(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    city: str | None = None,
    user: str | None = None,
    user_id: int | None = None,
    expiring: bool = False,
    expiring_24h: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
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
    conn_lookup: dict[int, tuple[str | None, str | None]] = {}
    if connection_ids:
        conn_rows = (
            await session.execute(
                select(Connection.id, Connection.carrier, Location.city)
                .outerjoin(Location, Location.id == Connection.location_id)
                .where(Connection.id.in_(connection_ids))
            )
        ).all()
        for cid, carrier, city_val in conn_rows:
            conn_lookup[cid] = (city_val, carrier)

    items = [
        _access_view(
            a,
            user_display=user_display_map.get(a.user_id, "—"),
            city=conn_lookup.get(a.connection_id, (None, None))[0],
            carrier=conn_lookup.get(a.connection_id, (None, None))[1],
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
    user_display, city, carrier = await _access_extras(session, access)
    return _access_view(access, user_display=user_display, city=city, carrier=carrier)


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
    user_display, city, carrier = await _access_extras(session, access)
    return _access_view(access, user_display=user_display, city=city, carrier=carrier)


@router.post("/accesses/{access_id}/rotate-ip")
async def admin_rotate_ip(
    access_id: str, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    access = await _get_access(session, access_id)
    await rotate_ip(session, access=access, actor=f"admin:{admin.id}")
    await audit.write(session, admin_id=admin.id, action="access.rotate_ip", entity="access",
                       entity_id=access.id)
    user_display, city, carrier = await _access_extras(session, access)
    return _access_view(access, user_display=user_display, city=city, carrier=carrier)


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
    user_display, city, carrier = await _access_extras(session, access)
    return _access_view(access, user_display=user_display, city=city, carrier=carrier)


# ── orders / payments ────────────────────────────────────────────────────
def _order_view(o: Order, *, user_display: str, provider: str | None) -> dict[str, Any]:
    return {
        "id": str(o.public_id),
        "user": user_display,
        "status": o.status,
        "provider": provider,
        "amount_usd": float(o.amount_usd),
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
    user_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(Order)
    count_stmt = select(func.count()).select_from(Order)
    if status:
        stmt = stmt.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)
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
    stmt = stmt.order_by(Order.created_at.desc())

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


class ResolveBody(BaseModel):
    action: str  # 'approve' | 'fail' | 'refund'


@router.post("/orders/{order_id}/resolve")
async def resolve_order(
    order_id: str, body: ResolveBody, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    order = await _get_order(session, order_id)
    if body.action == "approve":
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
    if not 0 < body.amount_usd <= float(order.amount_usd):
        raise ValidationError("refund amount must be > 0 and <= the order amount")
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
    order_id: str, body: MarkPaidBody, admin: Owner, session: DbSession
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
    rows = await session.execute(
        select(ReferralLedger.status, func.coalesce(func.sum(ReferralLedger.amount_usd), 0))
        .group_by(ReferralLedger.status)
    )
    return {status: float(total) for status, total in rows}


@router.get("/referrals/ledger")
async def referrals_ledger(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    referrer_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(ReferralLedger)
    count_stmt = select(func.count()).select_from(ReferralLedger)
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
    user_display_map = await _user_display_map(session, [entry.referrer_user_id for entry in rows])
    return {
        "items": [
            {
                "id": str(entry.id),
                "referrer_user_id": str(entry.referrer_user_id),
                "referrer": user_display_map.get(entry.referrer_user_id, "—"),
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
    }


@router.get("/payouts")
async def list_payouts(
    admin: CurrentAdmin, session: DbSession, status: str = "requested"
) -> dict[str, Any]:
    stmt = select(Payout).order_by(Payout.requested_at)
    if status:
        stmt = stmt.where(Payout.status == status)
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
        "referral_pct": await settings_svc.get(session, "referral_pct", 10),
        "referral_hold_days": await settings_svc.get(session, "referral_hold_days", 14),
        "referral_min_payout_usd": await settings_svc.get(session, "referral_min_payout_usd", 20),
    }


class ReferralSettingsPatch(BaseModel):
    referral_pct: float | None = Field(default=None, ge=0, le=100)
    referral_hold_days: int | None = Field(default=None, ge=0, le=365)
    referral_min_payout_usd: float | None = Field(default=None, ge=0)


@router.patch("/settings/referral")
async def patch_referral_settings(
    body: ReferralSettingsPatch, admin: Owner, session: DbSession
) -> dict[str, Any]:
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


# ── system ───────────────────────────────────────────────────────────────
@router.get("/settings")
async def get_all_settings(admin: Owner, session: DbSession) -> dict[str, Any]:
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
        "attribution",
    }
)


@router.patch("/settings")
async def patch_all_settings(
    body: SettingsPatch, admin: Owner, session: DbSession
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


@router.put("/terms")
async def put_terms(body: TermsBody, admin: Owner, session: DbSession) -> dict[str, Any]:
    tos = await settings_svc.get(session, "tos", {})
    next_version = int(tos.get("version") or 0) + 1
    new_tos = {"version": next_version, "text_md": body.text_md, "questions": body.questions}
    await settings_svc.set_value(session, "tos", new_tos, admin_id=admin.id)
    await audit.write(session, admin_id=admin.id, action="terms.update", entity="app_setting",
                       entity_id="tos", after={"version": next_version})
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
    }


@router.get("/admins")
async def list_admins(admin: Owner, session: DbSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(AdminUser).order_by(AdminUser.created_at))).scalars().all()
    return [_admin_user_view(a) for a in rows]


class AdminCreateBody(BaseModel):
    email: str
    password: str
    display_name: str
    role: str = "operator"


@router.post("/admins", status_code=201)
async def create_admin(
    body: AdminCreateBody, admin: Owner, session: DbSession
) -> dict[str, Any]:
    existing = await session.scalar(select(AdminUser.id).where(AdminUser.email == body.email))
    if existing is not None:
        raise Conflict("admin with this email already exists")
    new_admin = AdminUser(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
    )
    session.add(new_admin)
    await session.flush()
    await audit.write(session, admin_id=admin.id, action="admin.create", entity="admin_user",
                       entity_id=new_admin.id, after={"email": body.email, "role": body.role})
    return _admin_user_view(new_admin)


class AdminPatchBody(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@router.patch("/admins/{admin_id}")
async def patch_admin(
    admin_id: int, body: AdminPatchBody, admin: Owner, session: DbSession
) -> dict[str, Any]:
    target = await session.get(AdminUser, admin_id)
    if target is None:
        raise NotFound("admin not found")
    # Owner self-protection: an owner must not downgrade their own role or
    # deactivate themselves (would lock the system out of any active owner).
    if admin.id == admin_id:
        new_role = body.role
        new_is_active = body.is_active
        if (new_role is not None and new_role != "owner") or new_is_active is False:
            raise Conflict("cannot downgrade or deactivate self")
    updates = body.model_dump(exclude_unset=True, exclude={"password"})
    for field, value in updates.items():
        setattr(target, field, value)
    if body.password is not None:
        target.password_hash = hash_password(body.password)
        updates["password"] = "***"  # noqa: S105  redaction marker, not a real secret
    await audit.write(session, admin_id=admin.id, action="admin.update", entity="admin_user",
                       entity_id=target.id, after=updates)
    return _admin_user_view(target)


@router.get("/audit")
async def list_audit(
    admin: CurrentAdmin,
    session: DbSession,
    entity: str | None = None,
    admin_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
        count_stmt = count_stmt.where(AuditLog.entity == entity)
    if admin_id:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
        count_stmt = count_stmt.where(AuditLog.admin_id == admin_id)
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
