"""One search box per screen, a date range beside it, and Save that is not Publish.

Covers the two rules that are easy to break without noticing: a query has to match the
row as the console *prints* it (past-tense verbs against machine keys), and writing the
terms must not force every client to re-accept unless someone asked for that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from app.api import deps
from app.api.admin.domain import _search_terms
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import AuditLog, Payout, User
from httpx import ASGITransport, AsyncClient
from scripts.seed import (
    seed_admin,
    seed_dev_fixtures,
    seed_locations,
    seed_settings,
    seed_tariffs,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest_asyncio.fixture
async def client(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_tariffs(s)
        await seed_locations(s)
        await seed_admin(s)
        await s.flush()
        await seed_dev_fixtures(s)
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
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c
    app.dependency_overrides.clear()


# ── the stemmer ──────────────────────────────────────────────────────────
def test_past_tense_queries_reach_the_stored_key() -> None:
    """The screen says "Revoked"; the column says `access.revoke`. Both must meet."""
    for typed, stored in [
        ("revoked", "access.revoke"),
        ("updated", "tariff.update"),
        ("approved", "payout.approve"),
        ("banned", "client.ban"),
        ("unbanned", "client.unban"),
        ("published", "post.publish"),
        ("synced", "connection.sync"),
        ("marked", "order.mark_paid"),
    ]:
        (term,) = _search_terms(typed)
        assert term in stored, f"{typed!r} → {term!r} does not occur in {stored!r}"


def test_long_and_mixed_tokens_are_left_alone() -> None:
    """A hash is not a verb. Chopping two characters off one to guess at grammar
    would turn an exact lookup into a prefix scan."""
    txid = "31fc9598ede03b5105cc82b70687df245a29607fa16fdfb396e8d102ee5616a4"
    assert _search_terms(txid) == [txid]
    assert _search_terms("TMtvQXAP2f6mqnjJgTLMVUMcFEhivJaRhq") == [
        "tmtvqxap2f6mqnjjgtlmvumcfehivjarhq"
    ]
    # A four-letter name ending in "ed" is a name, not a past tense.
    assert _search_terms("fred") == ["fred"]


def test_words_are_required_together() -> None:
    assert _search_terms("app setting") == ["app", "setting"]


# ── audit log ────────────────────────────────────────────────────────────
async def test_audit_search_and_date_range(engine, client: AsyncClient) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add_all(
            [
                AuditLog(
                    admin_id=None, action="access.revoke", entity="access", entity_id="1",
                    created_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
                ),
                AuditLog(
                    admin_id=None, action="tariff.update", entity="tariff", entity_id="2",
                    created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
                ),
            ]
        )
        await s.commit()

    # typed as the row is printed
    r = await client.get("/api/admin/audit", params={"q": "revoked"})
    assert r.status_code == 200, r.text
    assert [i["action"] for i in r.json()["items"]] == ["access.revoke"]

    # both words must land, or the second one would widen instead of narrow
    assert (await client.get("/api/admin/audit", params={"q": "revoked tariff"})).json()["total"] == 0

    r = await client.get("/api/admin/audit", params={"since": "2026-08-05"})
    assert [i["action"] for i in r.json()["items"]] == ["tariff.update"]

    # the end of the range includes its own day
    r = await client.get("/api/admin/audit", params={"before": "2026-08-01"})
    assert [i["action"] for i in r.json()["items"]] == ["access.revoke"]


# ── clients ──────────────────────────────────────────────────────────────
async def test_clients_search_spans_columns(client: AsyncClient) -> None:
    # handle in one column, telegram id in another — one box, and both have to match
    r = await client.get("/api/admin/clients", params={"q": "dev 100001"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1

    assert (await client.get("/api/admin/clients", params={"q": "dev nobody"})).json()["total"] == 0
    # a partial id works like every other partial: it is matched as text
    assert (await client.get("/api/admin/clients", params={"q": "0000"})).json()["total"] == 1


# ── pool ─────────────────────────────────────────────────────────────────
async def test_connections_search_reaches_the_related_city(client: AsyncClient) -> None:
    everything = (await client.get("/api/admin/connections", params={"limit": 200})).json()
    assert everything["total"] > 0

    r = await client.get("/api/admin/connections", params={"q": "verizon", "limit": 200})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and all(i["carrier"] == "Verizon" for i in items)

    city = everything["items"][0]["city"]
    r = await client.get("/api/admin/connections", params={"q": city, "limit": 200})
    assert r.json()["items"] and all(i["city"] == city for i in r.json()["items"])


async def test_accesses_accepts_a_query(client: AsyncClient) -> None:
    """No fixtures issue an access here; this guards the SQL, which nests a subquery
    inside a subquery to reach the city and is the part that would fail loudly."""
    r = await client.get("/api/admin/accesses", params={"q": "verizon dallas"})
    assert r.status_code == 200, r.text


# ── payouts ──────────────────────────────────────────────────────────────
async def test_payouts_search_by_referrer_and_destination(engine, client: AsyncClient) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user_id = await s.scalar(select(User.id).where(User.tg_username == "dev_user"))
        s.add(
            Payout(
                referrer_user_id=user_id,
                amount_usd=Decimal("12.34"),
                wallet_address="TMtvQXAP2f6mqnjJgTLMVUMcFEhivJaRhq",
                network="trc20",
                status="requested",
                requested_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
        await s.commit()

    assert (await client.get("/api/admin/payouts")).json()["total"] == 1
    assert (await client.get("/api/admin/payouts", params={"q": "trc20"})).json()["total"] == 1
    assert (await client.get("/api/admin/payouts", params={"q": "dev_user"})).json()["total"] == 1
    assert (await client.get("/api/admin/payouts", params={"q": "TMtvQ"})).json()["total"] == 1
    assert (await client.get("/api/admin/payouts", params={"q": "bep20"})).json()["total"] == 0

    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    assert (await client.get("/api/admin/payouts", params={"since": tomorrow})).json()["total"] == 0


async def test_referral_ledger_accepts_a_query(client: AsyncClient) -> None:
    r = await client.get("/api/admin/referrals/ledger", params={"q": "dev_user", "since": "2026-01-01"})
    assert r.status_code == 200, r.text


# ── receiving wallets ────────────────────────────────────────────────────
async def test_payment_rails_lists_every_supported_rail(client: AsyncClient) -> None:
    """One list, not "accepting" plus a separate "supported but not configured".

    An operator who wants to start taking Litecoin should find that switch on the row that
    says Litecoin, not in a second panel that only says the coin exists.
    """
    r = await client.get("/api/admin/payment-rails")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["watching"] is (body["provider"] == "onchain")
    assert len(body["rails"]) == body["supported_count"]

    rails = {(x["asset"], x["network"]) for x in body["rails"]}
    assert ("LTC", "native") in rails
    assert ("USDT", "trc20") in rails


async def test_saving_rails_takes_over_from_the_env(client: AsyncClient) -> None:
    tron = "TMtvQXAP2f6mqnjJgTLMVUMcFEhivJaRhq"
    r = await client.put(
        "/api/admin/payment-rails",
        json={
            "rails": [
                {
                    "asset": "USDT",
                    "network": "trc20",
                    "address": tron,
                    "confirmations": 19,
                    # sent, and deliberately not stored — see normalise_rails
                    "min_amount_usd": 5,
                    "tolerance_pct": 0.5,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["console_managed"] is True

    saved = next(x for x in body["rails"] if (x["asset"], x["network"]) == ("USDT", "trc20"))
    assert saved["address"] == tron
    assert saved["confirmations"] == 19
    # A minimum and an underpayment tolerance are not dials this business has. Sending
    # them anyway must not quietly bring them back.
    assert "min_amount_usd" not in saved
    assert "tolerance_pct" not in saved

    # …and it survives a fresh read rather than living only in this process's memory
    again = (await client.get("/api/admin/payment-rails")).json()
    assert next(
        x for x in again["rails"] if (x["asset"], x["network"]) == ("USDT", "trc20")
    )["address"] == tron

    # clearing the address is how a wallet is removed — the rail stays listed, unaccepted
    cleared = await client.put(
        "/api/admin/payment-rails",
        json={"rails": [{"asset": "USDT", "network": "trc20", "address": ""}]},
    )
    assert cleared.status_code == 200, cleared.text
    assert next(
        x for x in cleared.json()["rails"] if (x["asset"], x["network"]) == ("USDT", "trc20")
    )["address"] == ""


async def test_an_address_from_the_wrong_chain_is_refused(client: AsyncClient) -> None:
    """The mistake people actually make: the right address on the wrong rail.

    It is a format check, not a checksum — it catches a Tron address pasted onto Ethereum,
    not two transposed characters. That is the difference between "obviously wrong" and
    "needs reading back against the wallet", and only the first one can be automated.
    """
    tron = "TMtvQXAP2f6mqnjJgTLMVUMcFEhivJaRhq"
    r = await client.put(
        "/api/admin/payment-rails",
        json={"rails": [{"asset": "USDT", "network": "erc20", "address": tron}]},
    )
    assert r.status_code == 422, r.text
    assert "ethereum" in r.text.lower()

    # a truncated paste is caught too
    short = await client.put(
        "/api/admin/payment-rails",
        json={"rails": [{"asset": "BTC", "network": "native", "address": "bc1qshort"}]},
    )
    assert short.status_code == 422, short.text

    # and a rail the watcher has no engine for
    unknown = await client.put(
        "/api/admin/payment-rails",
        json={"rails": [{"asset": "DOGE", "network": "native", "address": "D6hgd"}]},
    )
    assert unknown.status_code == 422, unknown.text


# ── terms ────────────────────────────────────────────────────────────────
async def test_saving_terms_keeps_the_version_publishing_bumps_it(client: AsyncClient) -> None:
    """The version is the re-acceptance gate. Every write used to bump it, so fixing a
    typo pushed the entire user base back through the acceptance screen."""
    before = (await client.get("/api/admin/terms")).json()
    assert before["version"]

    saved = await client.put(
        "/api/admin/terms",
        json={"text_md": "## Terms\n\nTypo fixed.", "questions": before["questions"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == before["version"]
    assert saved.json()["text_md"] == "## Terms\n\nTypo fixed."

    published = await client.put(
        "/api/admin/terms",
        json={
            "text_md": "## Terms\n\nSomething material.",
            "questions": before["questions"],
            "publish": True,
        },
    )
    assert published.json()["version"] == before["version"] + 1

    # and the questions survive the round trip in the shape the mini-app renders
    assert (await client.get("/api/admin/terms")).json()["questions"] == before["questions"]


async def test_payout_wallets_are_listed_and_saved(client: AsyncClient) -> None:
    """The other direction of the money flow: three rails, USDT only, editable."""
    body = (await client.get("/api/admin/payment-rails")).json()
    assert [w["network"] for w in body["payout_wallets"]] == ["trc20", "erc20", "bep20"]

    tron = "TMtvQXAP2f6mqnjJgTLMVUMcFEhivJaRhq"
    evm = "0x26EC3900000000000000000000000000000E0b1a"
    r = await client.put(
        "/api/admin/payment-rails",
        json={
            "rails": [],
            "payout_wallets": [
                {"network": "trc20", "address": tron},
                {"network": "erc20", "address": evm},
            ],
        },
    )
    assert r.status_code == 200, r.text
    saved = {w["network"]: w["address"] for w in r.json()["payout_wallets"]}
    assert saved == {"trc20": tron, "erc20": evm, "bep20": ""}

    # …and the same guard as a referrer's own payout address: right address, wrong rail
    wrong = await client.put(
        "/api/admin/payment-rails",
        json={"rails": [], "payout_wallets": [{"network": "erc20", "address": tron}]},
    )
    assert wrong.status_code == 422, wrong.text


async def test_an_address_for_the_other_network_says_so(client: AsyncClient) -> None:
    """The switchover in the wrong order is not a typo, and must not be reported as one.

    Someone pasting the client's real wallets in while the deployment is still on testnet
    gets told which way round it is, not "that is not a bitcoin address" — which would be
    both wrong and useless.
    """
    r = await client.put(
        "/api/admin/payment-rails",
        json={
            "rails": [
                # tests run against ONCHAIN_NETWORK=mainnet, so a testnet address is the
                # wrong-network case here
                {"asset": "BTC", "network": "native",
                 "address": "tb1qpev303lfxcfdxrzgzjf0f494lh6e9dwvc98lq8"}
            ]
        },
    )
    assert r.status_code == 422, r.text
    body = r.text.lower()
    assert "testnet bitcoin address" in body
    assert "onchain_network" in body


async def test_accesses_carry_and_are_found_by_their_order(engine, client: AsyncClient) -> None:
    """A package row has to say which purchase paid for it.

    The internal order_id is a key nobody can quote; the public one is what the customer
    reads off their receipt, what the payments ledger shows, and what a refund
    conversation opens with. Pasting it here must find the access it bought.
    """
    from app.models import Access, Connection, Order, Tariff

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user_id = await s.scalar(select(User.id).where(User.tg_username == "dev_user"))
        conn_id = await s.scalar(select(Connection.id).limit(1))
        tariff = Tariff(
            code="probe-daily", name="Probe", kind="auto",
            duration_minutes=1440, price_usd=10, auto_issue=True,
        )
        s.add(tariff)
        await s.flush()
        order = Order(
            user_id=user_id, tariff_id=tariff.id, tariff_code=tariff.code,
            duration_minutes=1440, amount_usd=10, status="paid",
        )
        s.add(order)
        await s.flush()
        s.add(
            Access(
                user_id=user_id, order_id=order.id, connection_id=conn_id,
                tariff_code=tariff.code, status="active",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await s.commit()
        order_public = str(order.public_id)

    listed = (await client.get("/api/admin/accesses")).json()
    row = next(r for r in listed["items"] if r["tariff_code"] == "probe-daily")
    assert row["order_public_id"] == order_public

    found = await client.get("/api/admin/accesses", params={"q": order_public})
    assert found.status_code == 200, found.text
    assert [r["order_public_id"] for r in found.json()["items"]] == [order_public]


# ── a query that matches nothing must show nothing ───────────────────────
async def test_a_query_that_matches_nothing_returns_nothing(client: AsyncClient) -> None:
    """Typing into the box and getting the whole table back is the worst answer available.

    It reads as "everything matches" when it means "your query fell through". The path
    here: the tokeniser listed A-Za-z, so two Cyrillic characters were two separators and
    reduced to no words, an empty term list meant no WHERE clause, and no WHERE clause is
    every row. Somebody with the wrong keyboard layout would have taken the table at face
    value.
    """
    everything = (await client.get("/api/admin/clients")).json()["total"]
    assert everything > 0

    for q in ("сл", "!!!", "…", "🙂"):
        r = await client.get("/api/admin/clients", params={"q": q})
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 0, f"{q!r} returned {r.json()['total']} of {everything}"

    # The same rule on the other screens that share the helper.
    for path in ("/api/admin/accesses", "/api/admin/connections", "/api/admin/audit"):
        r = await client.get(path, params={"q": "щщ"})
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 0, path


async def test_cyrillic_names_are_searchable(engine, client: AsyncClient) -> None:
    """Telegram first names are often Cyrillic, and the console lists them. Dropping those
    characters at the tokeniser made the whole column unsearchable — silently, because the
    answer was "here is everyone" rather than an error."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(User(tg_user_id=444_111, tg_username="ru_client", first_name="Николай",
                   referral_code="rucode"))
        await s.commit()

    for q in ("Николай", "никол", "НИКОЛ"):
        r = await client.get("/api/admin/clients", params={"q": q})
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 1, f"{q!r} → {r.json()['total']}"

    # …and a Cyrillic word that is in nobody's name still finds nobody.
    assert (await client.get("/api/admin/clients", params={"q": "Пётр"})).json()["total"] == 0


# ── orders: the same box and pills as every other screen ─────────────────
async def test_orders_search_filter_and_sort(engine, client: AsyncClient) -> None:
    """The orders list had no search and no filters, so answering "where is my order"
    meant paging through everything or opening clients one at a time.

    Four separate things have to hold, and each one has been wrong on some screen at some
    point: a number finds exactly that order and not every order containing the digit; a
    query nobody matches returns nothing rather than the whole table; the plan pill filters
    on the plan and not on the amount that happens to go with it; and sorting is done by
    the database, so it orders the whole result set rather than the current page.
    """
    from app.models import Order, Tariff

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user_id = await s.scalar(select(User.id).where(User.tg_username == "dev_user"))
        tariff = await s.scalar(select(Tariff).where(Tariff.code == "daily"))
        assert tariff is not None
        now = datetime.now(UTC)
        made = []
        for code, amount, status, age_days in (
            ("daily", Decimal("10.00"), "paid", 0),
            ("daily", Decimal("20.00"), "expired", 1),
            ("monthly", Decimal("85.00"), "completed", 40),
        ):
            o = Order(
                user_id=user_id, tariff_id=tariff.id, tariff_code=code,
                duration_minutes=1440, amount_usd=amount, status=status,
                created_at=now - timedelta(days=age_days),
            )
            s.add(o)
            made.append(o)
        await s.commit()
        numbers = [o.id for o in made]

    async def listed(**params: object) -> dict:
        r = await client.get("/api/admin/orders", params=params)
        assert r.status_code == 200, r.text
        return r.json()

    # The number a buyer quotes finds one row — not every order whose digits contain it.
    one = await listed(q=str(numbers[0]))
    assert [i["number"] for i in one["items"]] == [numbers[0]]
    assert one["total"] == 1
    # …and with the # they copied off the message.
    assert (await listed(q=f"#{numbers[0]}"))["total"] == 1

    # A handle reaches the orders of that client.
    assert (await listed(q="dev_user"))["total"] >= 3

    # Nothing matching must show nothing. Getting the table back reads as "everything
    # matches" when it means the query fell through.
    assert (await listed(q="no-such-buyer-anywhere"))["total"] == 0

    # The plan pill filters on the plan.
    monthly = await listed(tariff="monthly")
    assert monthly["total"] >= 1
    assert {i["tariff_code"] for i in monthly["items"]} == {"monthly"}

    # Sorting happens in the database, over everything — not over the page just fetched.
    asc = [i["amount_usd"] for i in (await listed(sort="amount_usd", order="asc"))["items"]]
    assert asc == sorted(asc)
    desc = [i["amount_usd"] for i in (await listed(sort="amount_usd", order="desc"))["items"]]
    assert desc == sorted(desc, reverse=True)

    # The date range is inclusive at both ends: "to today" has to include today.
    today = datetime.now(UTC).date().isoformat()
    assert (await listed(since=today))["total"] >= 1
    assert (await listed(before=today))["total"] >= 1
    old = await listed(before=(datetime.now(UTC) - timedelta(days=30)).date().isoformat())
    assert numbers[2] in [i["number"] for i in old["items"]]
    assert numbers[0] not in [i["number"] for i in old["items"]]


async def test_orders_carry_their_plan_and_quantity(engine, client: AsyncClient) -> None:
    """An order for $85 and one for $255 can be the same plan bought differently.

    The list showed only the amount, so a multi-proxy purchase was indistinguishable from
    a single one at a bigger tier — and the operator reading the row has no other place to
    learn which it was.
    """
    from app.models import Order, Tariff

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user_id = await s.scalar(select(User.id).where(User.tg_username == "dev_user"))
        tariff = await s.scalar(select(Tariff).where(Tariff.code == "daily"))
        assert tariff is not None
        o = Order(
            user_id=user_id, tariff_id=tariff.id, tariff_code="daily",
            duration_minutes=1440, amount_usd=Decimal("30.00"), status="paid", quantity=3,
        )
        s.add(o)
        await s.commit()
        number = o.id

    rows = (await client.get("/api/admin/orders", params={"q": str(number)})).json()["items"]
    assert len(rows) == 1
    assert rows[0]["tariff_code"] == "daily"
    assert rows[0]["quantity"] == 3
