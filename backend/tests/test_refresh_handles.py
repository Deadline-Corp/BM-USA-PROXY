"""Keeping @handles honest in the background.

Telegram never announces a rename, and the data it attaches to a bot message or a mini-app
request is cached by the client. Measured on production 2026-08-17: a client who had renamed
themselves hours earlier still arrived as their old handle, while getChat answered with the
new one straight away. So a visit is not enough — support searches for the handle a customer
just quoted and finds nobody.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import User
from app.services.users import refresh_handles
from sqlalchemy import select


class _Chat:
    def __init__(self, username: str | None, first_name: str | None = "Nick") -> None:
        self.username = username
        self.first_name = first_name
        self.last_name = None


class _StubBot:
    """get_chat per user id; ids listed in `broken` raise, as a blocked account does."""

    def __init__(self, handles: dict[int, str | None], broken: set[int] | None = None) -> None:
        self.handles = handles
        self.broken = broken or set()
        self.asked: list[int] = []

    async def get_chat(self, tg_user_id: int) -> _Chat:
        self.asked.append(tg_user_id)
        if tg_user_id in self.broken:
            raise RuntimeError("bot was blocked by the user")
        return _Chat(self.handles.get(tg_user_id))


def _user(tg_id: int, handle: str, *, seen_days_ago: int = 1, checked: datetime | None = None):
    return User(
        tg_user_id=tg_id,
        tg_username=handle,
        referral_code=f"RH{tg_id}",
        last_seen_at=datetime.now(UTC) - timedelta(days=seen_days_ago),
        handle_checked_at=checked,
    )


async def test_a_renamed_client_is_picked_up(session) -> None:
    session.add(_user(326361915, "NNick777888"))
    await session.flush()

    result = await refresh_handles(session, _StubBot({326361915: "NNick777"}))
    await session.flush()

    assert result == {"checked": 1, "changed": 1, "failed": 0}
    assert await session.scalar(select(User.tg_username)) == "NNick777"


async def test_an_unchanged_handle_is_not_reported_as_a_change(session) -> None:
    session.add(_user(1001, "same_handle"))
    await session.flush()

    result = await refresh_handles(session, _StubBot({1001: "same_handle"}))

    assert result == {"checked": 1, "changed": 0, "failed": 0}


async def test_a_blocked_account_does_not_stop_the_walk(session) -> None:
    session.add_all([_user(2001, "blocked_one"), _user(2002, "fine_one")])
    await session.flush()

    result = await refresh_handles(
        session, _StubBot({2002: "renamed_two"}, broken={2001})
    )
    await session.flush()

    assert result["failed"] == 1
    assert result["changed"] == 1
    # Stamped anyway, so the next pass moves on instead of retrying the same dead account.
    blocked = await session.scalar(select(User).where(User.tg_user_id == 2001))
    assert blocked is not None and blocked.handle_checked_at is not None


async def test_it_takes_the_least_recently_checked_first(session) -> None:
    """A fixed cost per pass only comes round if the walk advances."""
    now = datetime.now(UTC)
    session.add_all(
        [
            _user(3001, "checked_today", checked=now),
            _user(3002, "checked_last_week", checked=now - timedelta(days=7)),
            _user(3003, "never_checked", checked=None),
        ]
    )
    await session.flush()

    bot = _StubBot({3001: "a", 3002: "b", 3003: "c"})
    await refresh_handles(session, bot, batch=2)

    assert bot.asked == [3003, 3002], "never-checked first, then the oldest check"


async def test_a_long_dormant_client_is_left_alone(session) -> None:
    """Somebody who has not opened the app in a year does not need polling forever."""
    session.add(_user(4001, "dormant", seen_days_ago=400))
    await session.flush()

    bot = _StubBot({4001: "renamed"})
    result = await refresh_handles(session, bot, active_days=90)

    assert result == {"checked": 0, "changed": 0, "failed": 0}
    assert bot.asked == []
