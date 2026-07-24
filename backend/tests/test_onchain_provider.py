"""Unit tests for OnchainProvider.create_invoice (no DB; stub oracle + config)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from app.services.payments.onchain.config import OnchainConfigError, load_config
from app.services.payments.onchain.oracle import PriceOracle
from app.services.payments.onchain.provider import OnchainProvider
from app.services.payments.onchain.reference_allocator import b58encode, derive_reference

_METHODS = json.dumps(
    [
        {"asset": "USDT", "network": "trc20", "address": "TUSDTaddr"},
        {"asset": "SOL", "network": "native", "address": "SoLaddr"},
    ]
)


def _provider() -> OnchainProvider:
    async def src(_cg: str) -> Decimal:
        return Decimal("150")

    return OnchainProvider(config=load_config(_METHODS, "{}"), oracle=PriceOracle(source=src))


async def test_create_invoice_stablecoin() -> None:
    dto = await _provider().create_invoice(
        order_public_id="order-1", amount_usd=Decimal("30"), ttl_minutes=60,
        asset="USDT", network="trc20",
    )
    assert dto.pay_address == "TUSDTaddr"
    assert dto.crypto_currency == "USDT"
    assert dto.crypto_network == "trc20"
    assert dto.chain == "tron"
    assert dto.locked_rate == Decimal(1)
    assert dto.crypto_amount is not None and dto.crypto_amount >= Decimal("30")
    assert dto.reference_pubkey is None
    assert dto.expires_at_epoch > 0


async def test_create_invoice_volatile_has_reference() -> None:
    dto = await _provider().create_invoice(
        order_public_id="order-2", amount_usd=Decimal("30"), ttl_minutes=60,
        asset="SOL", network="native",
    )
    assert dto.chain == "solana"
    assert dto.locked_rate == Decimal("150")
    assert dto.crypto_amount is not None and dto.crypto_amount >= Decimal("0.2")
    assert dto.reference_pubkey  # Solana Pay reference is set


async def test_create_invoice_is_deterministic() -> None:
    p = _provider()
    a = await p.create_invoice(order_public_id="same", amount_usd=Decimal("5"),
                               ttl_minutes=10, asset="USDT", network="trc20")
    b = await p.create_invoice(order_public_id="same", amount_usd=Decimal("5"),
                               ttl_minutes=10, asset="USDT", network="trc20")
    assert a.crypto_amount == b.crypto_amount


async def test_create_invoice_defaults_to_first_method() -> None:
    dto = await _provider().create_invoice(
        order_public_id="o3", amount_usd=Decimal("5"), ttl_minutes=10
    )
    assert dto.crypto_network == "trc20"


async def test_create_invoice_unknown_rail_raises() -> None:
    with pytest.raises(OnchainConfigError):
        await _provider().create_invoice(
            order_public_id="o4", amount_usd=Decimal("5"), ttl_minutes=10,
            asset="DOGE", network="native",
        )


def test_reference_is_deterministic_base58() -> None:
    assert derive_reference("order-1") == derive_reference("order-1")
    assert derive_reference("order-1") != derive_reference("order-2")
    ref = derive_reference("order-1")
    # base58 excludes 0 O I l to avoid visual ambiguity
    assert ref and not (set(ref) & {"0", "O", "I", "l"})


def test_b58encode_preserves_leading_zeros() -> None:
    assert b58encode(b"\x00\x00\x01").startswith("11")
