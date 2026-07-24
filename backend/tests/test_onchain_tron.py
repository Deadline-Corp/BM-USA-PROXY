"""Tron client (TronGrid) tests — offline via a fake HTTP transport + one DB pipeline run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.models import Access, Invoice, Order, Tariff, User
from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.assets import USDT_TRC20
from app.services.payments.onchain.clients import build_client, chain_max_scan
from app.services.payments.onchain.clients.tron import TronClient
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select

ADDR = "TWatchedAddr11111111111111111111111"


class FakeHttp:
    """Routes requests to queued responses by URL suffix (endswith); FIFO per suffix."""

    def __init__(self) -> None:
        self._get: list[tuple[str, Any]] = []
        self._post: list[tuple[str, Any]] = []
        self.requests: list[tuple[str, str]] = []

    def on_get(self, suffix: str, *responses: Any) -> None:
        self._get.extend((suffix, r) for r in responses)

    def on_post(self, suffix: str, *responses: Any) -> None:
        self._post.extend((suffix, r) for r in responses)

    async def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
        self.requests.append(("GET", url))
        for i, (suf, resp) in enumerate(self._get):
            if url.endswith(suf):
                del self._get[i]
                return resp
        return {"data": [], "meta": {}}

    async def post(self, url: str, *, json: Any | None = None, headers: dict | None = None) -> Any:
        self.requests.append(("POST", url))
        for i, (suf, resp) in enumerate(self._post):
            if url.endswith(suf):
                del self._post[i]
                return resp
        return {}

    async def aclose(self) -> None:
        return None


def _nowblock(number: int, ts: int) -> dict:
    return {"block_header": {"raw_data": {"number": number, "timestamp": ts}}}


def _trc20_page(items: list[dict], fingerprint: str | None = None) -> dict:
    return {"data": items, "meta": ({"fingerprint": fingerprint} if fingerprint else {})}


def _trc20_item(txid: str, value: int, to_addr: str, *, block_ts: int, decimals: int = 6) -> dict:
    return {
        "transaction_id": txid,
        "token_info": {"symbol": "USDT", "decimals": decimals, "address": USDT_TRC20},
        "block_timestamp": block_ts,
        "from": "TSenderAddr000000000000000000000000",
        "to": to_addr,
        "type": "Transfer",
        "value": str(value),
    }


def _trx_item(txid: str, amount_sun: int, block_number: int) -> dict:
    return {
        "txID": txid,
        "blockNumber": block_number,
        "ret": [{"contractRet": "SUCCESS"}],
        "raw_data": {
            "contract": [
                {
                    "type": "TransferContract",
                    "parameter": {"value": {"amount": amount_sun, "owner_address": "41abc"}},
                }
            ]
        },
    }


def _tron_config(confirmations: int = 19, *, with_trx: bool = False):
    rails = [{"asset": "USDT", "network": "trc20", "address": ADDR, "confirmations": confirmations}]
    if with_trx:
        rails.append({"asset": "TRX", "network": "native", "address": ADDR})
    return load_config(json.dumps(rails), "{}")


# ── pure client unit tests ────────────────────────────────────────────────


async def test_get_block_height_returns_timestamp() -> None:
    http = FakeHttp()
    http.on_post("getnowblock", _nowblock(1000, 1700000000000))
    client = TronClient(endpoint="https://x", http=http)
    assert await client.get_block_height() == 1700000000000


async def test_scan_trc20_parses_amount_and_confirmations() -> None:
    now_ts = 1700000000000
    http = FakeHttp()
    http.on_post("getnowblock", _nowblock(1000, now_ts))
    http.on_get(
        "transactions/trc20",
        _trc20_page([_trc20_item("tx1", 10005000, ADDR, block_ts=now_ts - 60000)]),
    )
    client = TronClient(endpoint="https://x", http=http)
    res = await client.scan(
        from_block=now_ts - 900000, to_block=now_ts, methods=_tron_config().methods_for_chain("tron")
    )
    assert len(res) == 1
    t = res[0]
    assert t.asset == "USDT" and t.network == "trc20" and t.txid == "tx1"
    assert t.amount == Decimal("10.005")
    assert t.to_address == ADDR
    assert t.confirmations == 20  # 60000ms / 3000ms


async def test_scan_trc20_paginates() -> None:
    now_ts = 1700000000000
    http = FakeHttp()
    http.on_post("getnowblock", _nowblock(1000, now_ts))
    http.on_get(
        "transactions/trc20",
        _trc20_page([_trc20_item("tx1", 1000000, ADDR, block_ts=now_ts - 60000)], fingerprint="fp"),
        _trc20_page([_trc20_item("tx2", 2000000, ADDR, block_ts=now_ts - 60000)]),
    )
    client = TronClient(endpoint="https://x", http=http)
    res = await client.scan(
        from_block=0, to_block=now_ts, methods=_tron_config().methods_for_chain("tron")
    )
    assert {t.txid for t in res} == {"tx1", "tx2"}


async def test_scan_trx_native() -> None:
    http = FakeHttp()
    http.on_post("getnowblock", _nowblock(1000, 1700000000000))
    http.on_get("/transactions", _trc20_page([_trx_item("trxtx", 5_000_000, 990)]))
    client = TronClient(endpoint="https://x", http=http)
    res = await client.scan(
        from_block=0,
        to_block=1700000000000,
        methods=_tron_config(with_trx=True).methods_for_chain("tron"),
    )
    trx = [t for t in res if t.asset == "TRX"]
    assert len(trx) == 1
    assert trx[0].amount == Decimal("5")
    assert trx[0].confirmations == 11  # 1000 - 990 + 1


async def test_confirmations_from_block_number() -> None:
    http = FakeHttp()
    http.on_post("gettransactioninfobyid", {"blockNumber": 990})
    http.on_post("getnowblock", _nowblock(1000, 1700000000000))
    client = TronClient(endpoint="https://x", http=http)
    assert await client.confirmations("tx1") == 11


async def test_confirmations_unpacked_tx_is_zero() -> None:
    http = FakeHttp()
    http.on_post("gettransactioninfobyid", {})  # not yet in a block
    client = TronClient(endpoint="https://x", http=http)
    assert await client.confirmations("pending-tx") == 0


def test_factory_builds_tron_and_skips_others() -> None:
    cfg = load_config(
        json.dumps([{"asset": "USDT", "network": "trc20", "address": ADDR}]),
        json.dumps({"tron": {"url": "https://api.trongrid.io", "api_key": "k"}}),
    )
    client = build_client("tron", cfg)
    assert client is not None and client.chain == "tron"
    assert build_client("ethereum", cfg) is None
    assert chain_max_scan("tron") == 15 * 60 * 1000
    assert chain_max_scan("solana") == 500  # unconfigured chain → default window


# ── DB pipeline: real Tron client → watcher → activation ──────────────────


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()
    await seed_dev_fixtures(session)
    await session.flush()


async def _make_order(session, *, inv_id: str, expected: Decimal) -> tuple[Order, Invoice]:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    user = User(
        tg_user_id=abs(hash(inv_id)) % 9_000_000 + 1000,
        referral_code=inv_id.replace("-", "").upper()[:12],
    )
    session.add(user)
    await session.flush()
    order = Order(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_code="daily",
        duration_minutes=1440,
        amount_usd="10",
        status="awaiting_payment",
    )
    session.add(order)
    await session.flush()
    invoice = Invoice(
        order_id=order.id,
        provider="onchain",
        provider_invoice_id=inv_id,
        status="pending",
        amount_usd="10",
        crypto_currency="USDT",
        crypto_network="trc20",
        crypto_amount=expected,
        pay_address=ADDR,
        chain="tron",
        amount_tolerance=Decimal("0"),
        locked_rate=Decimal("1"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(invoice)
    await session.flush()
    return order, invoice


async def _access_count(session, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Access).where(Access.order_id == order_id)
        )
        or 0
    )


async def test_tron_client_drives_activation_through_watcher(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order, invoice = await _make_order(session, inv_id="tron-1", expected=expected)

    now_ts = 1700000000000
    http = FakeHttp()
    # run_chain_tick calls get_block_height() then scan() → two getnowblock reads
    http.on_post("getnowblock", _nowblock(1000, now_ts), _nowblock(1000, now_ts))
    http.on_get(
        "transactions/trc20",
        _trc20_page([_trc20_item("0xtrondep", 10005000, ADDR, block_ts=now_ts - 60000)]),
    )
    client = TronClient(endpoint="https://x", http=http)

    report = await run_chain_tick(session, client, config=_tron_config())

    assert report.transfers == 1
    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert invoice.matched_txid == "0xtrondep"
    assert await _access_count(session, order.id) == 1
