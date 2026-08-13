"""An admin account points at a Telegram account, and the pointer has to survive contact.

The login code will be delivered to a numeric chat id, which the console never sees and
cannot ask for. All it has is a handle somebody typed. The gap between the two is where
this can go wrong quietly — a handle bound to the wrong inbox sends an operator's sign-in
code to a stranger — so the binding rules are pinned down here rather than trusted.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.core.security import hash_password
from app.main import app
from app.models import AdminUser
from app.services.admin_telegram import InvalidHandle, bind_from_start, normalise_handle
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("@Ivan_K", "ivan_k"),
        ("Ivan_K", "ivan_k"),
        ("  @ivan_k  ", "ivan_k"),
        ("t.me/ivan_k", "ivan_k"),
        ("https://t.me/ivan_k", "ivan_k"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_handles_are_read_the_way_people_write_them(typed, stored) -> None:
    """Whatever the owner pastes — the @, the profile link, stray spaces — is one handle."""
    assert normalise_handle(typed) == stored


@pytest.mark.parametrize("typed", ["ab", "ivan k", "ivan-k", "1van", "@@ivan", "ivan!"])
def test_nonsense_is_refused(typed) -> None:
    with pytest.raises(InvalidHandle):
        normalise_handle(typed)


@pytest_asyncio.fixture
async def ctx(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
        await s.commit()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[deps.db_session] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as boss:
        pwd = settings.seed_admin_password
        assert pwd is not None
        r = await boss.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        boss.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield boss, maker
    app.dependency_overrides.clear()


async def _create(client, **over) -> dict:
    body = {
        "email": "op@test.local",
        "password": "operator-pw-1234",
        "display_name": "Operator",
        "telegram_username": "@Operator_One",
    }
    body.update(over)
    r = await client.post("/api/admin/admins", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_new_account_stores_the_handle_and_waits(ctx) -> None:
    boss, _ = ctx
    created = await _create(boss)
    assert created["telegram_username"] == "operator_one"
    # Nobody has opened the bot, so there is nowhere to send a code yet — and the console
    # says so instead of implying the account is ready.
    assert created["telegram_linked"] is False


async def test_pressing_start_binds_the_chat(ctx) -> None:
    boss, maker = ctx
    created = await _create(boss)
    async with maker() as s:
        assert await bind_from_start(s, handle="Operator_One", tg_user_id=777_001) is True
        await s.commit()
    rows = (await boss.get("/api/admin/admins")).json()
    row = next(a for a in rows if a["id"] == created["id"])
    assert row["telegram_linked"] is True


async def test_a_stranger_pressing_start_binds_nothing(ctx) -> None:
    """Almost everyone who opens this bot is a customer. They must not touch the console."""
    boss, maker = ctx
    await _create(boss)
    async with maker() as s:
        assert await bind_from_start(s, handle="some_customer", tg_user_id=777_002) is False
        assert await bind_from_start(s, handle=None, tg_user_id=777_003) is False
        await s.commit()


async def test_an_already_bound_handle_is_not_taken_over(ctx) -> None:
    """The attack this closes: an operator gives up their handle, someone else claims it on
    Telegram, presses Start, and starts receiving that operator's sign-in codes."""
    boss, maker = ctx
    await _create(boss)
    async with maker() as s:
        assert await bind_from_start(s, handle="operator_one", tg_user_id=777_010) is True
        await s.commit()
    async with maker() as s:
        assert await bind_from_start(s, handle="operator_one", tg_user_id=999_999) is False
        await s.commit()
    async with maker() as s:
        bound = await s.scalar(
            select(AdminUser.telegram_user_id).where(AdminUser.email == "op@test.local")
        )
    assert bound == 777_010


async def test_changing_the_handle_drops_the_old_binding(ctx) -> None:
    """A different handle means a different person — their codes must stop going to the
    inbox the previous one was bound to. This is how an operator is replaced."""
    boss, maker = ctx
    created = await _create(boss)
    async with maker() as s:
        await bind_from_start(s, handle="operator_one", tg_user_id=777_020)
        await s.commit()

    r = await boss.patch(
        f"/api/admin/admins/{created['id']}", json={"telegram_username": "@operator_two"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {**r.json(), "telegram_username": "operator_two", "telegram_linked": False}

    # The replacement binds on their own Start; the departed handle no longer matches.
    async with maker() as s:
        assert await bind_from_start(s, handle="operator_one", tg_user_id=777_020) is False
        assert await bind_from_start(s, handle="operator_two", tg_user_id=777_021) is True
        await s.commit()


async def test_clearing_the_handle_leaves_nothing_behind(ctx) -> None:
    boss, maker = ctx
    created = await _create(boss)
    async with maker() as s:
        await bind_from_start(s, handle="operator_one", tg_user_id=777_030)
        await s.commit()
    r = await boss.patch(f"/api/admin/admins/{created['id']}", json={"telegram_username": ""})
    assert r.status_code == 200, r.text
    assert r.json()["telegram_username"] is None
    assert r.json()["telegram_linked"] is False


async def test_leaving_the_field_out_does_not_wipe_it(ctx) -> None:
    """Renaming somebody must not silently cost them their second factor."""
    boss, _ = ctx
    created = await _create(boss)
    r = await boss.patch(f"/api/admin/admins/{created['id']}", json={"display_name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["telegram_username"] == "operator_one"


async def test_two_accounts_cannot_claim_one_handle(ctx) -> None:
    """Otherwise binding is a coin toss and codes land in the wrong console session."""
    boss, _ = ctx
    await _create(boss)
    r = await boss.post(
        "/api/admin/admins",
        json={
            "email": "op2@test.local",
            "password": "operator-pw-5678",
            "display_name": "Second",
            "telegram_username": "operator_one",
        },
    )
    assert r.status_code == 409, r.text


async def test_a_bad_handle_is_refused_at_the_door(ctx) -> None:
    boss, _ = ctx
    r = await boss.post(
        "/api/admin/admins",
        json={
            "email": "op3@test.local",
            "password": "operator-pw-9999",
            "display_name": "Third",
            "telegram_username": "not a handle",
        },
    )
    assert r.status_code == 422, r.text


async def test_an_account_without_a_handle_still_works(ctx) -> None:
    """Nothing about this is required yet — the field is optional until the code is."""
    boss, _ = ctx
    created = await _create(boss, email="op4@test.local", telegram_username=None)
    assert created["telegram_username"] is None
