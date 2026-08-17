"""Who an operator alert actually reaches.

Telegram only accepts an @username for a public channel; a private chat needs the numeric
id, and only after that person has started the bot. Operators do not think in ids, so the
handle they write is resolved here — and a handle that resolves to nobody is left alone,
because that is what a channel looks like.
"""

from __future__ import annotations

from app.models import AdminUser, User
from app.services import settings as settings_svc
from app.services.ops_alerts import OPS_CHATS_SETTING, ops_chat_ids


async def _set(session, value: str) -> None:
    await settings_svc.set_value(session, OPS_CHATS_SETTING, value)
    await session.flush()


async def test_a_client_handle_becomes_their_id(session) -> None:
    session.add(User(tg_user_id=6569763578, tg_username="usproxy_support", referral_code="OPS00001"))
    await session.flush()
    await _set(session, "@usproxy_support")

    assert await ops_chat_ids(session) == ["6569763578"]


async def test_the_handle_is_matched_regardless_of_case(session) -> None:
    session.add(User(tg_user_id=5869362397, tg_username="BMUsProxy", referral_code="OPS00002"))
    await session.flush()
    await _set(session, "@bmusproxy")

    assert await ops_chat_ids(session) == ["5869362397"]


async def test_a_console_account_resolves_too(session) -> None:
    """Support staff have console accounts and may never have bought anything."""
    session.add(
        AdminUser(
            email="ops@bmusproxy.local",
            display_name="Ops",
            password_hash="x",
            role="operator",
            telegram_username="ops_person",
            telegram_user_id=111222333,
        )
    )
    await session.flush()
    await _set(session, "@ops_person")

    assert await ops_chat_ids(session) == ["111222333"]


async def test_an_unknown_handle_is_passed_through(session) -> None:
    """A public channel is addressed exactly this way — dropping it would break delivery."""
    await _set(session, "@bm_usa_proxy_channel")

    assert await ops_chat_ids(session) == ["@bm_usa_proxy_channel"]


async def test_the_same_person_written_twice_is_told_once(session) -> None:
    session.add(User(tg_user_id=444555666, tg_username="dup_person", referral_code="OPS00003"))
    await session.flush()
    await _set(session, "@dup_person, 444555666")

    assert await ops_chat_ids(session) == ["444555666"]


async def test_plain_ids_still_work(session) -> None:
    await _set(session, "123456789, -1001234567890")

    assert await ops_chat_ids(session) == ["123456789", "-1001234567890"]
