"""Content: first-touch post attribution + broadcast audience materialization."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Broadcast, BroadcastDelivery, Channel, Post, User
from app.services import content


async def _post(session, code: str) -> Post:
    ch = Channel(tg_chat_id=hash(code) % 10_000_000, title="ch")
    session.add(ch)
    await session.flush()
    p = Post(channel_id=ch.id, title="t", body="b", deep_link_code=code, status="posted")
    session.add(p)
    await session.flush()
    return p


async def test_record_click_first_touch(session) -> None:
    post = await _post(session, "promo1")
    user = User(tg_user_id=808001, referral_code="CLICK001")
    session.add(user)
    await session.flush()

    await content.record_click(session, code="promo1", user=user)
    assert post.clicks == 1
    assert user.source_post_id == post.id

    # a second click keeps first-touch attribution but still counts the click
    other = await _post(session, "promo2")
    await content.record_click(session, code="promo2", user=user)
    assert other.clicks == 1
    assert user.source_post_id == post.id  # unchanged


async def test_record_click_unknown_code_is_noop(session) -> None:
    user = User(tg_user_id=808002, referral_code="CLICK002")
    session.add(user)
    await session.flush()
    await content.record_click(session, code="does-not-exist", user=user)
    assert user.source_post_id is None


async def test_materialize_broadcast_targets_active_users(session) -> None:
    for i in range(3):
        session.add(User(tg_user_id=809000 + i, referral_code=f"BC{i:06d}"))
    session.add(User(tg_user_id=809900, referral_code="BCBAN01", status="banned"))
    session.add(User(tg_user_id=809901, referral_code="BCBLK01", is_bot_blocked=True))
    await session.flush()

    bc = Broadcast(title="promo", body="hi", audience_filter={})
    session.add(bc)
    await session.flush()

    n = await content.materialize_broadcast(session, bc)
    assert n == 3  # banned + bot-blocked excluded
    assert bc.total_count == 3
    deliveries = await session.scalar(
        select(func.count()).select_from(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == bc.id
        )
    )
    assert deliveries == 3
