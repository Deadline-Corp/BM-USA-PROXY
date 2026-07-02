"""Admin domain API: dashboard, clients, tariffs, pool, accesses, orders, requests,
referrals, broadcasts, publications, faq, notifications, system settings.

Stage 2 scope: iproxy sync/broadcast-send/post-publish are stubbed (Stage 3/4 workers
own the real dispatch); everything else is fully wired against the real tables.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
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
from app.services import audit
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
    return {
        "revenue": {"today": revenue_today, "d7": revenue_7d, "d30": revenue_30d},
        "active_accesses": active_accesses,
        "free_pool": free_pool,
        "pending_manual_review": pending_manual_review,
        "new_requests": new_requests,
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
            WHERE status = 'completed' AND paid_at >= now() - (:days || ' days')::interval
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
    items = []
    for (user,) in rows:
        total_spent = await session.scalar(
            select(func.coalesce(func.sum(Order.amount_usd), 0)).where(
                Order.user_id == user.id, Order.status == "completed"
            )
        )
        active_count = await session.scalar(
            select(func.count()).select_from(Access).where(
                Access.user_id == user.id, Access.status.in_(_ACTIVE_ACCESS)
            )
        )
        items.append(
            {
                "id": user.id,
                "tg_user_id": user.tg_user_id,
                "tg_username": user.tg_username,
                "first_name": user.first_name,
                "email": user.email,
                "status": user.status,
                "total_spent": float(total_spent or 0),
                "active": int(active_count or 0),
                "created_at": user.created_at.isoformat(),
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
    ledger = (
        (await session.execute(
            select(ReferralLedger)
            .where(ReferralLedger.referrer_user_id == user.id)
            .order_by(ReferralLedger.created_at.desc())
        )).scalars().all()
    )

    return {
        "profile": {
            "id": user.id,
            "tg_user_id": user.tg_user_id,
            "tg_username": user.tg_username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "status": user.status,
            "operator_note": user.operator_note,
            "created_at": user.created_at.isoformat(),
            "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
        },
        "tos": {
            "accepted": tos_row is not None,
            "version": tos_row.version if tos_row else None,
            "accepted_at": tos_row.accepted_at.isoformat() if tos_row else None,
            "answers": tos_row.answers if tos_row else {},
        },
        "accesses": [
            {
                "public_id": str(a.public_id),
                "tariff_code": a.tariff_code,
                "status": a.status,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in accesses
        ],
        "orders": [
            {
                "public_id": str(o.public_id),
                "tariff_code": o.tariff_code,
                "amount_usd": float(o.amount_usd),
                "status": o.status,
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ],
        "referral": {
            "code": user.referral_code,
            "referred_count": referred_count,
            "ledger": [
                {
                    "id": entry.id,
                    "kind": entry.kind,
                    "amount_usd": float(entry.amount_usd),
                    "status": entry.status,
                    "created_at": entry.created_at.isoformat(),
                }
                for entry in ledger
            ],
        },
        "requests": [
            {"id": r.id, "type": r.type, "subject": r.subject, "status": r.status}
            for r in requests
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
    user.status = "banned"
    await audit.write(session, admin_id=admin.id, action="client.ban", entity="user",
                       entity_id=user.id)
    return {"status": user.status}


@router.post("/clients/{client_id}/unban")
async def unban_client(client_id: int, admin: CurrentAdmin, session: DbSession) -> dict[str, str]:
    user = await _get_user(session, client_id)
    user.status = "active"
    await audit.write(session, admin_id=admin.id, action="client.unban", entity="user",
                       entity_id=user.id)
    return {"status": user.status}


class ClientMessage(BaseModel):
    text: str


@router.post("/clients/{client_id}/message")
async def message_client(
    client_id: int, body: ClientMessage, admin: CurrentAdmin, session: DbSession
) -> dict[str, bool]:
    user = await _get_user(session, client_id)
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
def _connection_view(c: Connection) -> dict[str, Any]:
    return {
        "id": c.id,
        "iproxy_connection_id": c.iproxy_connection_id,
        "name": c.name,
        "location_id": c.location_id,
        "carrier": c.carrier,
        "tier": c.tier,
        "is_sellable": c.is_sellable,
        "online_status": c.online_status,
        "last_online_at": c.last_online_at.isoformat() if c.last_online_at else None,
        "health_note": c.health_note,
        "synced_at": c.synced_at.isoformat() if c.synced_at else None,
    }


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
    return {"items": [_connection_view(c) for c in rows], "total": total}


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
    return _connection_view(conn)


@router.post("/connections/sync")
async def sync_connections(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    return {"synced": False, "detail": "real iproxy sync in Stage 3"}


@router.get("/pool/summary")
async def pool_summary(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT
                l.city,
                c.carrier,
                count(*) AS total,
                count(*) FILTER (WHERE c.is_sellable) AS sellable,
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
            GROUP BY l.city, c.carrier
            ORDER BY l.city NULLS LAST, c.carrier NULLS LAST
            """
        )
    )
    return [
        {
            "city": r[0],
            "carrier": r[1],
            "total": int(r[2]),
            "sellable": int(r[3]),
            "free": int(r[4]),
            "busy": int(r[5]),
            "offline": int(r[6]),
        }
        for r in rows
    ]


# ── accesses (packages) ─────────────────────────────────────────────────
def _access_view(a: Access) -> dict[str, Any]:
    return {
        "public_id": str(a.public_id),
        "user_id": a.user_id,
        "connection_id": a.connection_id,
        "tariff_code": a.tariff_code,
        "status": a.status,
        "starts_at": a.starts_at.isoformat() if a.starts_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "rotations_count": a.rotations_count,
        "swap_count": a.swap_count,
        "created_at": a.created_at.isoformat(),
    }


@router.get("/accesses")
async def list_admin_accesses(
    admin: CurrentAdmin,
    session: DbSession,
    status: str | None = None,
    city: str | None = None,
    user_id: int | None = None,
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
    if city:
        conn_ids = select(Connection.id).join(
            Location, Location.id == Connection.location_id
        ).where(Location.city.ilike(f"%{city}%"))
        stmt = stmt.where(Access.connection_id.in_(conn_ids))
        count_stmt = count_stmt.where(Access.connection_id.in_(conn_ids))
    if expiring_24h:
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
    return {"items": [_access_view(a) for a in rows], "total": total}


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
    return _access_view(access)


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
    return _access_view(access)


@router.post("/accesses/{access_id}/rotate-ip")
async def admin_rotate_ip(
    access_id: str, admin: CurrentAdmin, session: DbSession
) -> dict[str, Any]:
    access = await _get_access(session, access_id)
    await rotate_ip(session, access=access, actor=f"admin:{admin.id}")
    await audit.write(session, admin_id=admin.id, action="access.rotate_ip", entity="access",
                       entity_id=access.id)
    return _access_view(access)


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
    return _access_view(access)


# ── orders / payments ────────────────────────────────────────────────────
def _order_view(o: Order) -> dict[str, Any]:
    return {
        "public_id": str(o.public_id),
        "user_id": o.user_id,
        "tariff_code": o.tariff_code,
        "amount_usd": float(o.amount_usd),
        "status": o.status,
        "origin": o.origin,
        "is_extension": o.is_extension,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        "completed_at": o.completed_at.isoformat() if o.completed_at else None,
        "created_at": o.created_at.isoformat(),
    }


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
    return {"items": [_order_view(o) for o in rows], "total": total}


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
    return {
        **_order_view(order),
        "invoice": (
            {
                "provider": invoice.provider,
                "status": invoice.status,
                "amount_usd": float(invoice.amount_usd),
                "pay_address": invoice.pay_address,
                "expires_at": invoice.expires_at.isoformat(),
            }
            if invoice is not None
            else None
        ),
        "payment_events": [
            {
                "id": e.id,
                "provider": e.provider,
                "signature_valid": e.signature_valid,
                "received_at": e.received_at.isoformat(),
                "processing_result": e.processing_result,
            }
            for e in events
        ],
    }


@router.get("/payments/manual-review")
async def manual_review_orders(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Order).where(Order.status == "manual_review").order_by(Order.created_at)
        )
    ).scalars().all()
    return [_order_view(o) for o in rows]


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
    return _order_view(order)


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

    await enqueue(
        session, user_id=order.user_id, template_code="refund_processed",
        payload={"order_public_id": str(order.public_id), "amount_usd": body.amount_usd},
    )
    await audit.write(session, admin_id=admin.id, action="order.refund", entity="order",
                       entity_id=order.id, after={"refund_id": refund.id,
                                                   "amount_usd": body.amount_usd})
    return {"order": _order_view(order), "refund_id": refund.id}


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
    return _order_view(order)


# ── requests (kanban) ────────────────────────────────────────────────────
def _request_view(r: Request) -> dict[str, Any]:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "type": r.type,
        "subject": r.subject,
        "body": r.body,
        "status": r.status,
        "assignee_id": r.assignee_id,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


@router.get("/requests")
async def list_requests(
    admin: CurrentAdmin, session: DbSession, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Request).order_by(Request.updated_at.desc())
    if status:
        stmt = stmt.where(Request.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [_request_view(r) for r in rows]


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
    return _request_view(req)


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
    return {"id": comment.id, "body": comment.body, "created_at": comment.created_at.isoformat()}


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
    return {
        "items": [
            {
                "id": entry.id,
                "referrer_user_id": entry.referrer_user_id,
                "referee_user_id": entry.referee_user_id,
                "order_id": entry.order_id,
                "kind": entry.kind,
                "amount_usd": float(entry.amount_usd),
                "status": entry.status,
                "hold_until": entry.hold_until.isoformat() if entry.hold_until else None,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in rows
        ],
        "total": total,
    }


def _payout_view(p: Payout) -> dict[str, Any]:
    return {
        "id": p.id,
        "referrer_user_id": p.referrer_user_id,
        "amount_usd": float(p.amount_usd),
        "wallet_address": p.wallet_address,
        "network": p.network,
        "status": p.status,
        "tx_hash": p.tx_hash,
        "reject_reason": p.reject_reason,
        "requested_at": p.requested_at.isoformat(),
        "processed_at": p.processed_at.isoformat() if p.processed_at else None,
    }


@router.get("/payouts")
async def list_payouts(
    admin: CurrentAdmin, session: DbSession, status: str = "requested"
) -> list[dict[str, Any]]:
    stmt = select(Payout).order_by(Payout.requested_at)
    if status:
        stmt = stmt.where(Payout.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [_payout_view(p) for p in rows]


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
    return _payout_view(payout)


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
    return _payout_view(payout)


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
    return _payout_view(payout)


@router.get("/settings/referral")
async def get_referral_settings(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    return {
        "referral_pct": await settings_svc.get(session, "referral_pct", 10),
        "referral_hold_days": await settings_svc.get(session, "referral_hold_days", 14),
        "referral_min_payout_usd": await settings_svc.get(session, "referral_min_payout_usd", 20),
    }


class ReferralSettingsPatch(BaseModel):
    referral_pct: float | None = None
    referral_hold_days: int | None = None
    referral_min_payout_usd: float | None = None


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
    return {
        "id": b.id,
        "title": b.title,
        "body": b.body,
        "audience_filter": b.audience_filter,
        "status": b.status,
        "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
        "total_count": b.total_count,
        "sent_count": b.sent_count,
        "failed_count": b.failed_count,
        "created_at": b.created_at.isoformat(),
    }


@router.get("/broadcasts")
async def list_broadcasts(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(Broadcast).order_by(Broadcast.created_at.desc()))
    ).scalars().all()
    return [_broadcast_view(b) for b in rows]


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
        "sent": broadcast.sent_count,
        "failed": broadcast.failed_count,
        "status": broadcast.status,
    }


# ── publications (channels / posts) ─────────────────────────────────────
def _channel_view(c: Channel) -> dict[str, Any]:
    return {
        "id": c.id,
        "tg_chat_id": c.tg_chat_id,
        "title": c.title,
        "username": c.username,
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
        "id": p.id,
        "channel_id": p.channel_id,
        "title": p.title,
        "body": p.body,
        "deep_link_code": p.deep_link_code,
        "status": p.status,
        "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "clicks": p.clicks,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/posts")
async def list_posts(admin: CurrentAdmin, session: DbSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Post).order_by(Post.created_at.desc()))).scalars().all()
    return [_post_view(p) for p in rows]


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
        "id": f.id,
        "category": f.category,
        "question": f.question,
        "answer": f.answer,
        "sort_order": f.sort_order,
        "is_active": f.is_active,
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
    return {
        "items": [
            {
                "id": n.id,
                "user_id": n.user_id,
                "template_code": n.template_code,
                "status": n.status,
                "attempts": n.attempts,
                "last_error": n.last_error,
                "scheduled_at": n.scheduled_at.isoformat(),
                "sent_at": n.sent_at.isoformat() if n.sent_at else None,
            }
            for n in rows
        ],
        "total": total,
    }


@router.get("/notifications/settings")
async def get_notification_settings(admin: CurrentAdmin, session: DbSession) -> dict[str, Any]:
    from app.services.notifications import TEMPLATES

    texts = {}
    for code in TEMPLATES:
        texts[code] = await settings_svc.get(session, f"notify_texts:{code}", "")
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


@router.patch("/settings")
async def patch_all_settings(
    body: SettingsPatch, admin: Owner, session: DbSession
) -> dict[str, Any]:
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
    return {
        "items": [
            {
                "id": a.id,
                "admin_id": a.admin_id,
                "action": a.action,
                "entity": a.entity,
                "entity_id": a.entity_id,
                "before": a.before,
                "after": a.after,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
        "total": total,
    }
