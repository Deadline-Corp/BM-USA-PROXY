"""EVM client (Ethereum/BSC) tests — offline via a fake JSON-RPC + one DB pipeline run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.models import Access, Invoice, Order, Tariff, User
from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.clients import build_client, chain_max_scan
from app.services.payments.onchain.clients.evm import _TRANSFER_TOPIC, EvmClient, _addr_topic
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select

ADDR = "0x1111111111111111111111111111111111111111"


class FakeRpc:
    """Routes JSON-RPC POSTs by method name; FIFO queue of results per method."""

    def __init__(self) -> None:
        self._by_method: dict[str, list[Any]] = {}
        self.calls: list[str] = []

    def on(self, method: str, *results: Any) -> None:
        self._by_method.setdefault(method, []).extend(results)

    async def post(self, url: str, *, json: Any | None = None, headers: dict | None = None) -> Any:
        method = json["method"]
        self.calls.append(method)
        queue = self._by_method.get(method) or []
        result = queue.pop(0) if queue else None
        return {"jsonrpc": "2.0", "id": json.get("id"), "result": result}

    async def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
        return {}

    async def aclose(self) -> None:
        return None


def _log(txid: str, amount_base: int, *, block_number: int, log_index: int = 0) -> dict:
    return {
        "transactionHash": txid,
        "blockNumber": hex(block_number),
        "logIndex": hex(log_index),
        "data": hex(amount_base),
        "topics": [
            _TRANSFER_TOPIC,
            _addr_topic("0x2222222222222222222222222222222222222222"),
            _addr_topic(ADDR),
        ],
    }


def _evm_config(chain: str, asset: str, network: str, confirmations: int = 12):
    return load_config(
        json.dumps(
            [{"asset": asset, "network": network, "address": ADDR, "confirmations": confirmations}]
        ),
        json.dumps({chain: {"url": "https://rpc"}}),
    )


# ── pure client unit tests ────────────────────────────────────────────────


async def test_scan_token_logs() -> None:
    rpc = FakeRpc()
    rpc.on("eth_blockNumber", hex(120))
    rpc.on("eth_getLogs", [_log("0xabc", 10005000, block_number=100)])  # USDC 6dp → 10.005
    client = EvmClient(chain="ethereum", endpoint="https://rpc", http=rpc)
    res = await client.scan(
        from_block=1,
        to_block=120,
        methods=_evm_config("ethereum", "USDC", "erc20").methods_for_chain("ethereum"),
    )
    assert len(res) == 1
    t = res[0]
    assert t.asset == "USDC" and t.network == "erc20" and t.txid == "0xabc"
    assert t.amount == Decimal("10.005")
    assert t.to_address == ADDR
    assert t.confirmations == 21  # 120 - 100 + 1


async def test_scan_token_bep20_18_decimals() -> None:
    rpc = FakeRpc()
    rpc.on("eth_blockNumber", hex(50))
    rpc.on("eth_getLogs", [_log("0xbnb", 5 * 10**18, block_number=40)])  # BEP20 USDT 18dp → 5
    client = EvmClient(chain="bsc", endpoint="https://rpc", http=rpc)
    res = await client.scan(
        from_block=1,
        to_block=50,
        methods=_evm_config("bsc", "USDT", "bep20").methods_for_chain("bsc"),
    )
    assert res[0].amount == Decimal("5")


async def test_scan_native_eth() -> None:
    rpc = FakeRpc()
    rpc.on("eth_blockNumber", hex(105))
    rpc.on(
        "eth_getBlockByNumber",
        {"transactions": [{"to": ADDR, "value": hex(10**18), "hash": "0xeth", "from": "0x3"}]},
        {"transactions": []},
    )
    client = EvmClient(chain="ethereum", endpoint="https://rpc", http=rpc)
    res = await client.scan(
        from_block=100,
        to_block=101,
        methods=_evm_config("ethereum", "ETH", "native").methods_for_chain("ethereum"),
    )
    assert len(res) == 1
    assert res[0].asset == "ETH" and res[0].amount == Decimal("1") and res[0].txid == "0xeth"
    assert res[0].confirmations == 6  # 105 - 100 + 1


async def test_confirmations_from_receipt() -> None:
    rpc = FakeRpc()
    rpc.on("eth_getTransactionReceipt", {"blockNumber": hex(100)})
    rpc.on("eth_blockNumber", hex(112))
    client = EvmClient(chain="ethereum", endpoint="https://rpc", http=rpc)
    assert await client.confirmations("0xabc") == 13


async def test_confirmations_dropped_tx_is_zero() -> None:
    rpc = FakeRpc()
    rpc.on("eth_getTransactionReceipt", None)
    client = EvmClient(chain="ethereum", endpoint="https://rpc", http=rpc)
    assert await client.confirmations("0xmissing") == 0


def test_factory_builds_evm_chains() -> None:
    eth = build_client("ethereum", _evm_config("ethereum", "USDC", "erc20"))
    assert eth is not None and eth.chain == "ethereum"
    bsc = build_client("bsc", _evm_config("bsc", "USDT", "bep20"))
    assert bsc is not None and bsc.chain == "bsc"
    # EVM needs a provider URL — no endpoint → not built
    no_ep = load_config(json.dumps([{"asset": "USDC", "network": "erc20", "address": ADDR}]), "{}")
    assert build_client("ethereum", no_ep) is None
    assert chain_max_scan("ethereum") == 100
    assert chain_max_scan("bsc") == 200


# ── DB pipeline: real EVM client → watcher → activation ───────────────────


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
        crypto_currency="USDC",
        crypto_network="erc20",
        crypto_amount=expected,
        pay_address=ADDR,
        chain="ethereum",
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


async def test_evm_client_drives_activation_through_watcher(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order, invoice = await _make_order(session, inv_id="evm-1", expected=expected)

    rpc = FakeRpc()
    # get_block_height() + scan()'s head read → two eth_blockNumber; block 118 @ head 120,
    # threshold 3 → 3 confirmations → finalize in one tick
    rpc.on("eth_blockNumber", hex(120), hex(120))
    rpc.on("eth_getLogs", [_log("0xevmdep", 10005000, block_number=118)])
    client = EvmClient(chain="ethereum", endpoint="https://rpc", http=rpc)
    cfg = _evm_config("ethereum", "USDC", "erc20", confirmations=3)

    report = await run_chain_tick(session, client, config=cfg, max_blocks=100)

    assert report.transfers == 1
    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert invoice.matched_txid == "0xevmdep"
    assert await _access_count(session, order.id) == 1
