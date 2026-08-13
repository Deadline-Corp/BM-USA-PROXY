"""Signing in takes the password and a code sent to Telegram.

The password is the secret that travels — reused, written down, typed on somebody else's
laptop. The code is the one that cannot: it is minted at the moment of the attempt and goes
to a phone. What is pinned down here is the seam between the two, because every way this
fails quietly ends with somebody in the console who should not be:

  * a password that stops at step one must buy nothing at all;
  * a code that could not be delivered must not become a way in;
  * six digits are only worth something while guesses are counted.
"""

from __future__ import annotations

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.core.security import hash_password
from app.main import app
from app.models import AdminUser
from app.services import admin_otp
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

OP = "otp-op@test.local"
OP_PW = "otp-operator-pw-12"
CHAT_ID = 555_444_333


@pytest_asyncio.fixture
async def ctx(engine, monkeypatch):
    """One account with Telegram bound, one without, and a stand-in for the bot."""
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
        s.add(
            AdminUser(
                email=OP, display_name="Bound Operator", role="operator",
                password_hash=hash_password(OP_PW), is_active=True,
                telegram_username="bound_op", telegram_user_id=CHAT_ID,
            )
        )
        await s.commit()

    sent: list[tuple[int, str]] = []

    async def fake_deliver(chat_id: int, code: str) -> None:
        sent.append((chat_id, code))

    monkeypatch.setattr(admin_otp, "deliver", fake_deliver)

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[deps.db_session] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, sent, maker, monkeypatch
    app.dependency_overrides.clear()


async def _password_step(client) -> dict:
    r = await client.post("/api/admin/auth/login", json={"email": OP, "password": OP_PW})
    assert r.status_code == 200, r.text
    return r.json()


async def test_an_account_without_telegram_signs_in_as_before(ctx) -> None:
    """The second factor arrives with the binding. Nobody is locked out by a setting."""
    client, sent, _, _ = ctx
    pwd = settings.seed_admin_password
    assert pwd is not None
    r = await client.post(
        "/api/admin/auth/login",
        json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
    )
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()
    assert sent == []


async def test_the_password_alone_gets_nothing(ctx) -> None:
    """Step one hands back a ticket, and a ticket is not a session."""
    client, sent, _, _ = ctx
    body = await _password_step(client)
    assert body["otp_required"] is True
    assert "access_token" not in body
    assert client.cookies.get("bm_refresh") is None
    assert body["sent_to"] == "@bound_op"
    # …and the code went to the bound chat, not anywhere the browser can see.
    assert len(sent) == 1
    assert sent[0][0] == CHAT_ID
    assert "code" not in body and sent[0][1] not in str(body)


async def test_the_code_completes_the_sign_in(ctx) -> None:
    client, sent, _, _ = ctx
    body = await _password_step(client)
    r = await client.post(
        "/api/admin/auth/login/otp", json={"ticket": body["ticket"], "code": sent[0][1]}
    )
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    me = await client.get("/api/admin/me")
    assert me.status_code == 200
    assert me.json()["email"] == OP


async def test_a_code_works_once(ctx) -> None:
    """Replay of a code seen over somebody's shoulder must not open a second session."""
    client, sent, _, _ = ctx
    body = await _password_step(client)
    payload = {"ticket": body["ticket"], "code": sent[0][1]}
    assert (await client.post("/api/admin/auth/login/otp", json=payload)).status_code == 200
    assert (await client.post("/api/admin/auth/login/otp", json=payload)).status_code == 401


async def test_a_wrong_guess_does_not_burn_the_ticket(ctx) -> None:
    """Fat fingers are normal; one typo must not send you back to the password."""
    client, sent, _, _ = ctx
    body = await _password_step(client)
    wrong = await client.post(
        "/api/admin/auth/login/otp", json={"ticket": body["ticket"], "code": "000000"}
    )
    assert wrong.status_code in (401, 200)  # 200 only if the code really was 000000
    if wrong.status_code == 200:
        return
    r = await client.post(
        "/api/admin/auth/login/otp", json={"ticket": body["ticket"], "code": sent[0][1]}
    )
    assert r.status_code == 200, r.text


async def test_guesses_run_out(ctx) -> None:
    """Six digits are a million possibilities only while you cannot try them all."""
    client, sent, _, _ = ctx
    body = await _password_step(client)
    real = sent[0][1]
    for i in range(admin_otp.MAX_ATTEMPTS):
        guess = f"{(int(real) + i + 1) % 1_000_000:06d}"
        r = await client.post(
            "/api/admin/auth/login/otp", json={"ticket": body["ticket"], "code": guess}
        )
        assert r.status_code == 401, r.text
    # The ticket is spent. Even the right code is no good now — start again.
    r = await client.post(
        "/api/admin/auth/login/otp", json={"ticket": body["ticket"], "code": real}
    )
    assert r.status_code == 401, r.text


async def test_an_invented_ticket_is_refused(ctx) -> None:
    client, _, _, _ = ctx
    r = await client.post(
        "/api/admin/auth/login/otp", json={"ticket": "made-up-ticket", "code": "123456"}
    )
    assert r.status_code == 401


async def test_a_code_that_could_not_be_sent_is_not_a_way_in(ctx) -> None:
    """Otherwise the second factor switches itself off for whoever blocks the bot."""
    client, _, _, monkeypatch = ctx

    async def broken(chat_id: int, code: str) -> None:
        raise admin_otp.DeliveryFailed("bot blocked by user")

    monkeypatch.setattr(admin_otp, "deliver", broken)
    r = await client.post("/api/admin/auth/login", json={"email": OP, "password": OP_PW})
    assert r.status_code == 503, r.text
    assert "Telegram" in r.json()["error"]["message"]
    assert client.cookies.get("bm_refresh") is None


async def test_switching_the_account_off_mid_login_stops_it(ctx) -> None:
    """The gap between the two steps is a real window — it must not outlive the account."""
    client, sent, maker, _ = ctx
    body = await _password_step(client)
    async with maker() as s:
        target = await s.scalar(select(AdminUser).where(AdminUser.email == OP))
        target.is_active = False
        await s.commit()
    r = await client.post(
        "/api/admin/auth/login/otp", json={"ticket": body["ticket"], "code": sent[0][1]}
    )
    assert r.status_code == 401, r.text


async def test_a_wrong_password_never_sends_a_code(ctx) -> None:
    """Otherwise anyone could ring an operator's phone at will, all night."""
    client, sent, _, _ = ctx
    r = await client.post("/api/admin/auth/login", json={"email": OP, "password": "nope"})
    assert r.status_code == 401
    assert sent == []
