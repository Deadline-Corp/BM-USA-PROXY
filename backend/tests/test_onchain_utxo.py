"""UTXO client (Bitcoin/Litecoin, Esplora) tests — offline + one DB pipeline run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.models import Access, Invoice, Order, Tariff, User
from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.clients import build_client, chain_max_scan
from app.services.payments.onchain.clients.utxo import UtxoClient
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select

ADDR = "bc1qwatchedaddr000000000000000000000000000"


class FakeHttp:
    """Routes GETs by ordered URL-substring rules; FIFO responses per rule."""

    def __init__(self) -> None:
        self._rules: list[list[Any]] = []

    def on(self, substr: str, *responses: Any) -> None:
        self._rules.append([substr, list(responses)])

    async def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
        for rule in self._rules:
            if rule[0] in url and rule[1]:
                return rule[1].pop(0)
        return []

    async def post(self, url: str, *, json: Any | None = None, headers: dict | None = None) -> Any:
        return {}

    async def aclose(self) -> None:
        return None


def _tx(
    txid: str,
    address: str,
    value_sats: int,
    *,
    block_height: int | None = None,
    confirmed: bool = True,
    extra_vouts: list[dict] | None = None,
) -> dict:
    vout = (extra_vouts or []) + [{"scriptpubkey_address": address, "value": value_sats}]
    status: dict[str, Any] = {"confirmed": confirmed}
    if confirmed and block_height is not None:
        status["block_height"] = block_height
    return {"txid": txid, "vout": vout, "status": status}


def _btc_config(confirmations: int = 2):
    return load_config(
        json.dumps([{"asset": "BTC", "network": "native", "address": ADDR,
                     "confirmations": confirmations}]),
        json.dumps({"bitcoin": {"url": "https://mempool.space/api"}}),
    )


# ── pure client unit tests ────────────────────────────────────────────────


async def test_get_block_height() -> None:
    http = FakeHttp()
    http.on("/blocks/tip/height", 800000)
    client = UtxoClient(chain="bitcoin", endpoint="https://x/api", http=http)
    assert await client.get_block_height() == 800000


async def test_scan_confirmed_output() -> None:
    http = FakeHttp()
    http.on("/blocks/tip/height", 800000)
    http.on("/txs", [_tx("btc1", ADDR, 50_000_000, block_height=799990)])  # 0.5 BTC
    client = UtxoClient(chain="bitcoin", endpoint="https://x/api", http=http)
    res = await client.scan(
        from_block=799000, to_block=800000, methods=_btc_config().methods_for_chain("bitcoin")
    )
    assert len(res) == 1
    t = res[0]
    assert t.asset == "BTC" and t.amount == Decimal("0.5") and t.txid == "btc1"
    assert t.confirmations == 11  # 800000 - 799990 + 1


async def test_scan_ignores_outputs_to_other_addresses() -> None:
    http = FakeHttp()
    http.on("/blocks/tip/height", 800000)
    http.on(
        "/txs",
        [
            _tx(
                "btc2", ADDR, 10_000_000, block_height=799995,
                extra_vouts=[{"scriptpubkey_address": "bc1qchange", "value": 999}],
            )
        ],
    )
    client = UtxoClient(chain="bitcoin", endpoint="https://x/api", http=http)
    res = await client.scan(
        from_block=799000, to_block=800000, methods=_btc_config().methods_for_chain("bitcoin")
    )
    assert len(res) == 1
    assert res[0].amount == Decimal("0.1")


async def test_scan_mempool_is_zero_conf() -> None:
    http = FakeHttp()
    http.on("/blocks/tip/height", 800000)
    http.on("/txs", [_tx("btc3", ADDR, 25_000_000, confirmed=False)])
    client = UtxoClient(chain="bitcoin", endpoint="https://x/api", http=http)
    res = await client.scan(
        from_block=799000, to_block=800000, methods=_btc_config().methods_for_chain("bitcoin")
    )
    assert len(res) == 1
    assert res[0].confirmations == 0


async def test_confirmations() -> None:
    http = FakeHttp()
    http.on("/tx/", {"status": {"confirmed": True, "block_height": 799990}})
    http.on("/blocks/tip/height", 800000)
    client = UtxoClient(chain="bitcoin", endpoint="https://x/api", http=http)
    assert await client.confirmations("btc1") == 11


async def test_confirmations_unconfirmed_is_zero() -> None:
    http = FakeHttp()
    http.on("/tx/", {"status": {"confirmed": False}})
    client = UtxoClient(chain="bitcoin", endpoint="https://x/api", http=http)
    assert await client.confirmations("mempool-tx") == 0


def test_factory_builds_utxo_with_default_endpoints() -> None:
    cfg = load_config(json.dumps([{"asset": "BTC", "network": "native", "address": ADDR}]), "{}")
    btc = build_client("bitcoin", cfg)
    assert btc is not None and btc.chain == "bitcoin"
    ltc_cfg = load_config(json.dumps([{"asset": "LTC", "network": "native", "address": ADDR}]), "{}")
    ltc = build_client("litecoin", ltc_cfg)
    assert ltc is not None and ltc.chain == "litecoin"
    assert chain_max_scan("bitcoin") == 10_000


# ── DB pipeline: real UTXO client → watcher → activation ──────────────────


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
        crypto_currency="BTC",
        crypto_network="native",
        crypto_amount=expected,
        pay_address=ADDR,
        chain="bitcoin",
        amount_tolerance=Decimal("0"),
        locked_rate=Decimal("60000"),
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


async def test_utxo_client_drives_activation_through_watcher(session) -> None:
    await _seed(session)
    expected = Decimal("0.00500000")  # 500000 sats
    order, invoice = await _make_order(session, inv_id="btc-1", expected=expected)

    tip = 800000
    http = FakeHttp()
    http.on("/blocks/tip/height", tip, tip)  # get_block_height() + scan()
    http.on("/txs", [_tx("0xbtcdep", ADDR, 500_000, block_height=799998)])  # confs = 3 ≥ 2
    client = UtxoClient(chain="bitcoin", endpoint="https://mempool.space/api", http=http)

    report = await run_chain_tick(session, client, config=_btc_config())

    assert report.transfers == 1
    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert invoice.matched_txid == "0xbtcdep"
    assert await _access_count(session, order.id) == 1
