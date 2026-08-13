"""Deleting a console account without making the past anonymous.

Three screens print an admin's name out of `admin_users`: the audit log, the client
conversation, and publication comments. Drop the row and every one of them answers "who did
this" with a dash — at the exact moment somebody is asking, which is usually the reason the
account is being removed in the first place.

So the account is what goes, not the record of it. What is checked here is both halves: it
disappears from the list, cannot sign in, and gives up its email and handle; and an audit
entry it wrote a week ago still says its name.
"""

from __future__ import annotations

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.core.security import hash_password
from app.main import app
from app.models import AdminUser, AuditLog
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

VICTIM = "delete-me@test.local"
VICTIM_PW = "wrong-account-pw"


@pytest_asyncio.fixture
async def ctx(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
        s.add(
            AdminUser(
                email=VICTIM, display_name="Wrongly Created", role="operator",
                password_hash=hash_password(VICTIM_PW), is_active=True,
                telegram_username="wrong_one",
            )
        )
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        pwd = settings.seed_admin_password
        assert pwd is not None
        r = await c.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c, maker
    app.dependency_overrides.clear()


async def _victim_id(maker) -> int:
    async with maker() as s:
        return await s.scalar(select(AdminUser.id).where(AdminUser.email == VICTIM))


async def test_it_leaves_the_list(ctx) -> None:
    boss, maker = ctx
    victim = await _victim_id(maker)
    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200
    assert [a["email"] for a in (await boss.get("/api/admin/admins")).json()] == [
        settings.seed_admin_email
    ]


async def test_it_cannot_sign_in_afterwards(ctx) -> None:
    boss, maker = ctx
    victim = await _victim_id(maker)
    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as gone:
        r = await gone.post(
            "/api/admin/auth/login", json={"email": VICTIM, "password": VICTIM_PW}
        )
    assert r.status_code == 401, r.text


async def test_an_open_session_ends_at_once(ctx) -> None:
    """Not at cookie expiry — the point of deleting somebody is that they are out now."""
    boss, maker = ctx
    victim = await _victim_id(maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as theirs:
        r = await theirs.post(
            "/api/admin/auth/login", json={"email": VICTIM, "password": VICTIM_PW}
        )
        assert r.status_code == 200, r.text
        theirs.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        assert (await theirs.get("/api/admin/me")).status_code == 200  # working before

        assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200

        assert (await theirs.get("/api/admin/me")).status_code in (401, 403)
        assert (await theirs.post("/api/admin/auth/refresh")).status_code == 401


async def test_what_they_did_still_carries_their_name(ctx) -> None:
    """The reason the row is kept. An entry written before the deletion has to keep saying
    who wrote it, or the audit log stops answering the only question it exists for."""
    boss, maker = ctx
    victim = await _victim_id(maker)
    async with maker() as s:
        s.add(AuditLog(admin_id=victim, action="access.revoke", entity="access",
                       entity_id="7"))
        await s.commit()

    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200

    rows = (await boss.get("/api/admin/audit")).json()["items"]
    revoke = next(r for r in rows if r["action"] == "access.revoke")
    assert revoke["admin"] == "Wrongly Created", revoke

    # …and the deletion itself is on the record, with the address that was released.
    deletion = next(r for r in rows if r["action"] == "admin.delete")
    assert deletion["admin"] == "Owner"


async def test_the_email_and_handle_come_free(ctx) -> None:
    """Recreating the account you just deleted, correctly this time, is the next thing an
    operator does — so both identifiers have to be available again."""
    boss, maker = ctx
    victim = await _victim_id(maker)
    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200
    r = await boss.post(
        "/api/admin/admins",
        json={
            "email": VICTIM,
            "password": "replacement-pw-1",
            "display_name": "Done Properly",
            "telegram_username": "wrong_one",
        },
    )
    assert r.status_code == 201, r.text


async def test_you_cannot_delete_the_account_you_are_using(ctx) -> None:
    """It would sign you out with no way back — and if it is the only one, nobody in."""
    boss, maker = ctx
    async with maker() as s:
        me = await s.scalar(
            select(AdminUser.id).where(AdminUser.email == settings.seed_admin_email)
        )
    assert (await boss.delete(f"/api/admin/admins/{me}")).status_code == 409
    assert (await boss.get("/api/admin/me")).status_code == 200


async def test_deleting_it_twice_is_a_clean_404(ctx) -> None:
    boss, maker = ctx
    victim = await _victim_id(maker)
    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200
    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 404
    assert (await boss.delete("/api/admin/admins/999999")).status_code == 404


async def test_nothing_else_is_swept_up(ctx) -> None:
    """A cascade would have taken the log with it."""
    boss, maker = ctx
    victim = await _victim_id(maker)
    async with maker() as s:
        s.add(AuditLog(admin_id=None, action="tariff.update", entity="tariff", entity_id="1"))
        await s.commit()
        before = await s.scalar(select(func.count()).select_from(AuditLog))

    assert (await boss.delete(f"/api/admin/admins/{victim}")).status_code == 200
    async with maker() as s:
        after = await s.scalar(select(func.count()).select_from(AuditLog))
    assert after == before + 1  # only the deletion entry was added
