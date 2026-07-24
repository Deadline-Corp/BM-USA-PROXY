"""Solana client tests — offline via a fake JSON-RPC + one DB pipeline run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.models import Access, Invoice, Order, Tariff, User
from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.assets import USDC_SPL
from app.services.payments.onchain.clients import build_client, chain_max_scan
from app.services.payments.onchain.clients.solana import SolanaClient
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select

OWNER = "SoLOwnerAddr1111111111111111111111111111111"
ATA = "SoLTokenAcct2222222222222222222222222222222"


class FakeRpc:
    def __init__(self) -> None:
        self._by_method: dict[str, list[Any]] = {}

    def on(self, method: str, *results: Any) -> None:
        self._by_method.setdefault(method, []).extend(results)

    async def post(self, url: str, *, json: Any | None = None, headers: dict | None = None) -> Any:
        method = json["method"]
        queue = self._by_method.get(method) or []
        result = queue.pop(0) if queue else None
        return {"jsonrpc": "2.0", "id": json.get("id"), "result": result}

    async def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
        return {}

    async def aclose(self) -> None:
        return None


def _sig(signature: str, slot: int, err: Any = None) -> dict:
    return {"signature": signature, "slot": slot, "err": err}


def _tx_native(address: str, lamports_delta: int, slot: int) -> dict:
    return {
        "slot": slot,
        "meta": {"err": None, "preBalances": [10**9], "postBalances": [10**9 + lamports_delta]},
        "transaction": {"message": {"accountKeys": [{"pubkey": address}]}},
    }


def _tx_spl(ata: str, mint: str, amount_base: int, slot: int, pre_amount: int = 0) -> dict:
    return {
        "slot": slot,
        "meta": {
            "err": None,
            "preTokenBalances": [
                {"accountIndex": 1, "mint": mint, "uiTokenAmount": {"amount": str(pre_amount)}}
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": mint, "uiTokenAmount": {"amount": str(amount_base)}}
            ],
        },
        "transaction": {"message": {"accountKeys": [{"pubkey": OWNER}, {"pubkey": ata}]}},
    }


def _sol_config(asset: str, network: str, address: str):
    return load_config(
        json.dumps([{"asset": asset, "network": network, "address": address}]),
        json.dumps({"solana": {"url": "https://rpc"}}),
    )


# ── pure client unit tests ────────────────────────────────────────────────


async def test_get_block_height_returns_slot() -> None:
    rpc = FakeRpc()
    rpc.on("getSlot", 12345)
    client = SolanaClient(endpoint="https://rpc", http=rpc)
    assert await client.get_block_height() == 12345


async def test_scan_native_sol() -> None:
    rpc = FakeRpc()
    rpc.on("getSlot", 1000)
    rpc.on("getSignaturesForAddress", [_sig("sig1", 990)], [])
    rpc.on("getTransaction", _tx_native(OWNER, 2 * 10**9, 990))  # 2 SOL
    client = SolanaClient(endpoint="https://rpc", http=rpc)
    res = await client.scan(
        from_block=1, to_block=1000, methods=_sol_config("SOL", "native", OWNER).methods_for_chain("solana")
    )
    assert len(res) == 1
    assert res[0].asset == "SOL" and res[0].amount == Decimal("2") and res[0].txid == "sig1"
    assert res[0].confirmations == 10  # 1000 - 990


async def test_scan_spl_usdc() -> None:
    rpc = FakeRpc()
    rpc.on("getSlot", 1000)
    rpc.on("getSignaturesForAddress", [_sig("sig2", 995)], [])
    rpc.on("getTransaction", _tx_spl(ATA, USDC_SPL, 10005000, 995))  # 10.005 USDC (6dp)
    client = SolanaClient(endpoint="https://rpc", http=rpc)
    res = await client.scan(
        from_block=1, to_block=1000, methods=_sol_config("USDC", "spl", ATA).methods_for_chain("solana")
    )
    assert len(res) == 1
    assert res[0].asset == "USDC" and res[0].network == "spl"
    assert res[0].amount == Decimal("10.005")


async def test_scan_skips_failed_tx() -> None:
    rpc = FakeRpc()
    rpc.on("getSlot", 1000)
    rpc.on("getSignaturesForAddress", [_sig("bad", 990, err={"InstructionError": []})], [])
    client = SolanaClient(endpoint="https://rpc", http=rpc)
    res = await client.scan(
        from_block=1, to_block=1000, methods=_sol_config("SOL", "native", OWNER).methods_for_chain("solana")
    )
    assert res == []


async def test_confirmations_finalized() -> None:
    rpc = FakeRpc()
    rpc.on("getSignatureStatuses", {"value": [{"slot": 990, "confirmationStatus": "finalized"}]})
    rpc.on("getSlot", 1000)
    client = SolanaClient(endpoint="https://rpc", http=rpc)
    assert await client.confirmations("sig1") == 10


async def test_confirmations_not_finalized_is_zero() -> None:
    rpc = FakeRpc()
    rpc.on("getSignatureStatuses", {"value": [{"slot": 990, "confirmationStatus": "confirmed"}]})
    client = SolanaClient(endpoint="https://rpc", http=rpc)
    assert await client.confirmations("sig1") == 0


def test_factory_builds_solana() -> None:
    cfg = _sol_config("USDC", "spl", ATA)
    client = build_client("solana", cfg)
    assert client is not None and client.chain == "solana"
    # default endpoint used when none configured
    no_ep = load_config(json.dumps([{"asset": "SOL", "network": "native", "address": OWNER}]), "{}")
    assert build_client("solana", no_ep) is not None
    assert chain_max_scan("solana") == 10_000


# ── DB pipeline: real Solana client → watcher → activation ────────────────


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
        crypto_network="spl",
        crypto_amount=expected,
        pay_address=ATA,
        chain="solana",
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


async def test_solana_client_drives_activation_through_watcher(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order, invoice = await _make_order(session, inv_id="sol-1", expected=expected)

    rpc = FakeRpc()
    rpc.on("getSlot", 1000, 1000)  # get_block_height() + scan()
    # slot must be within the fresh cursor window (init = head-5 → from_block 996)
    rpc.on("getSignaturesForAddress", [_sig("soldep", 998)], [])
    rpc.on("getTransaction", _tx_spl(ATA, USDC_SPL, 10005000, 998))
    client = SolanaClient(endpoint="https://rpc", http=rpc)

    report = await run_chain_tick(session, client, config=_sol_config("USDC", "spl", ATA))

    assert report.transfers == 1
    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert invoice.matched_txid == "soldep"
    assert await _access_count(session, order.id) == 1
