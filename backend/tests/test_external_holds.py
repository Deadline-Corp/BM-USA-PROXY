"""Phones occupied inside iproxy, with no row of ours saying so.

Someone creates a proxy-access straight in the iproxy console — or iproxy creates one
itself, as it does with "this proxy was created automatically" — and that phone is serving
traffic while our pool counts it free and the allocator happily sells it again.

The detection existed and reported nothing for weeks, because the client read the wrong
envelope key off iproxy's response (`items`, which iproxy never returns) and so saw an
empty list for every connection. Measured 2026-08-17: two phones showing credentials in
the iproxy console, `external_access_count = 0` on both, "Busy 0" on the pool screen.
"""

from __future__ import annotations

from typing import Any

from app.models import Access, Connection, Location, Order, Tariff, User
from app.services.provisioning.iproxy import IproxyClient
from app.services.provisioning.sync import sync_external_holds
from sqlalchemy import select


class _StubIproxy:
    """Returns iproxy's real envelope shape, keyed by connection."""

    def __init__(self, by_connection: dict[str, list[dict[str, Any]]]) -> None:
        self.by_connection = by_connection

    async def list_proxy_access(self, connection_id: str) -> list[dict[str, Any]]:
        return self.by_connection.get(connection_id, [])


def test_the_client_reads_iproxys_own_envelope_key(monkeypatch) -> None:
    """`proxy_accesses`, not `items` — the bug that made every phone look free."""
    payload = {
        "proxy_accesses": [
            {"id": "fc7ieiwgaz", "listen_service": "http", "port": 18732},
            {"id": "gg8jfjxhb0", "listen_service": "socks5", "port": 18733},
        ]
    }

    async def fake_request(self, method, path, *, json=None):
        return payload

    monkeypatch.setattr(IproxyClient, "_request", fake_request)

    import asyncio

    got = asyncio.get_event_loop().run_until_complete(
        IproxyClient().list_proxy_access("bfrysjo6yz")
    )
    assert [a["id"] for a in got] == ["fc7ieiwgaz", "gg8jfjxhb0"]


async def _pool(session):
    loc = Location(city="Oshkosh", state_code="WI")
    session.add(loc)
    await session.flush()
    conns = [
        Connection(
            iproxy_connection_id=cid,
            name=cid,
            location_id=loc.id,
            carrier="Verizon",
            is_sellable=True,
            online_status="online",
        )
        for cid in ("held-1", "clean-1")
    ]
    session.add_all(conns)
    await session.flush()
    return conns


async def test_an_access_we_did_not_issue_marks_the_phone_held(session) -> None:
    conns = await _pool(session)
    client = _StubIproxy({"held-1": [{"id": "made-in-the-console"}]})

    result = await sync_external_holds(session, client)  # type: ignore[arg-type]
    await session.flush()

    assert result == {"checked": 2, "held": 1}
    counts = {
        c.iproxy_connection_id: c.external_access_count
        for c in (await session.scalars(select(Connection))).all()
    }
    assert counts == {"held-1": 1, "clean-1": 0}
    assert all(c.external_checked_at is not None for c in conns)


async def test_our_own_live_access_is_not_counted_as_foreign(session) -> None:
    """Otherwise every phone we legitimately sold would take itself off the market."""
    conns = await _pool(session)
    tariff = Tariff(code="t-ext", name="Ext", kind="auto", duration_minutes=60, price_usd=1)
    user = User(tg_user_id=960001, referral_code="EXTH0001")
    session.add_all([tariff, user])
    await session.flush()
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-ext", amount_usd=1)
    session.add(order)
    await session.flush()
    session.add(
        Access(
            user_id=user.id,
            order_id=order.id,
            connection_id=conns[0].id,
            tariff_code="t-ext",
            status="active",
            iproxy_access_id="ours-http",
            iproxy_socks5_access_id="ours-socks",
        )
    )
    await session.flush()

    client = _StubIproxy({"held-1": [{"id": "ours-http"}, {"id": "ours-socks"}]})
    result = await sync_external_holds(session, client)  # type: ignore[arg-type]
    await session.flush()

    assert result["held"] == 0
    held = await session.scalar(
        select(Connection.external_access_count).where(Connection.id == conns[0].id)
    )
    assert held == 0


async def test_a_phone_we_could_not_ask_keeps_its_previous_answer(session) -> None:
    """"The request failed" is not the same statement as "nobody is holding it"."""
    conns = await _pool(session)
    conns[0].external_access_count = 2
    await session.flush()

    class _Broken(_StubIproxy):
        async def list_proxy_access(self, connection_id: str) -> list[dict[str, Any]]:
            if connection_id == "held-1":
                raise RuntimeError("iproxy is down")
            return []

    result = await sync_external_holds(session, _Broken({}))  # type: ignore[arg-type]
    await session.flush()

    assert result["checked"] == 1  # only the reachable one
    still_held = await session.scalar(
        select(Connection.external_access_count).where(Connection.id == conns[0].id)
    )
    assert still_held == 2


async def test_freeing_a_phone_in_iproxy_clears_the_hold_on_the_next_walk(session) -> None:
    """The other direction — the one the client actually exercises.

    A hold that appears must also disappear: the client frees the phone in the iproxy
    console, the next walk finds no foreign accesses, and the count returns to zero. The
    walk always writes what it saw, so this needs no special "clearing" code path — but
    nothing proved it, and the Sync now button spent weeks not running the walk at all.
    """
    conns = await _pool(session)
    held = conns[0]
    held.external_access_count = 1

    result = await sync_external_holds(session, _StubIproxy({}))  # type: ignore[arg-type]
    await session.flush()
    await session.refresh(held)

    assert result == {"checked": 2, "held": 0}
    assert held.external_access_count == 0
