"""Content & attribution: post-click tracking, channel posting, broadcasts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Access,
    Broadcast,
    BroadcastDelivery,
    Channel,
    Post,
    User,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def record_click(session: AsyncSession, *, code: str, user: User) -> None:
    """A user opened the bot via a channel post's deep link (?start=p_<code>)."""
    post = await session.scalar(select(Post).where(Post.deep_link_code == code))
    if post is None:
        return
    post.clicks += 1
    if user.source_post_id is None:  # first-touch attribution
        user.source_post_id = post.id


# ── channel posting (worker: publish_scheduled_posts) ───────────────────
async def publish_due_posts(session: AsyncSession, bot: Bot) -> int:
    now = _utcnow()
    posts = (
        await session.execute(
            select(Post).where(Post.status == "scheduled", Post.scheduled_at <= now)
        )
    ).scalars().all()
    if not posts:
        return 0
    me = await bot.get_me()
    posted = 0
    for post in posts:
        channel = await session.get(Channel, post.channel_id)
        if channel is None:
            post.status = "failed"
            continue
        link = f"https://t.me/{me.username}?start=p_{post.deep_link_code}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Get proxy →", url=link)]]
        )
        try:
            msg = await bot.send_message(channel.tg_chat_id, post.body, reply_markup=kb)
            post.status = "posted"
            post.posted_at = now
            post.tg_message_id = msg.message_id
            posted += 1
        except Exception:  # noqa: BLE001
            post.status = "failed"
    return posted


# ── broadcasts (worker: run scheduled/sending broadcasts) ───────────────
def _audience_select(broadcast: Broadcast) -> Any:
    f: dict[str, Any] = broadcast.audience_filter or {}
    stmt = select(User.id).where(User.status == "active", User.is_bot_blocked.is_(False))
    if f.get("has_active_access"):
        stmt = stmt.where(
            exists().where(
                Access.user_id == User.id,
                Access.status.in_(("active", "expiring")),
            )
        )
    if f.get("is_referrer"):
        stmt = stmt.where(exists().where(User.id == User.referrer_user_id))
    return stmt


async def materialize_broadcast(session: AsyncSession, broadcast: Broadcast) -> int:
    ids = (await session.execute(_audience_select(broadcast))).scalars().all()
    for uid in ids:
        stmt = insert(BroadcastDelivery).values(broadcast_id=broadcast.id, user_id=uid)
        stmt = stmt.on_conflict_do_nothing(index_elements=["broadcast_id", "user_id"])
        await session.execute(stmt)
    broadcast.total_count = len(ids)
    return len(ids)


async def send_broadcast_batch(
    session: AsyncSession, bot: Bot, broadcast: Broadcast, *, limit: int = 500
) -> int:
    rows = (
        await session.execute(
            select(BroadcastDelivery)
            .where(BroadcastDelivery.broadcast_id == broadcast.id,
                   BroadcastDelivery.status == "pending")
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    for d in rows:
        user = await session.get(User, d.user_id)
        if user is None:
            d.status = "failed"
            continue
        try:
            await bot.send_message(user.tg_user_id, broadcast.body)
            d.status = "sent"
            d.sent_at = _utcnow()
            broadcast.sent_count += 1
        except Exception as exc:  # noqa: BLE001
            d.status = "failed"
            d.error = str(exc)[:200]
            broadcast.failed_count += 1
    remaining = await session.scalar(
        select(func.count()).select_from(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == broadcast.id,
            BroadcastDelivery.status == "pending",
        )
    )
    if not remaining:
        broadcast.status = "done"
        broadcast.finished_at = _utcnow()
    return len(rows)
