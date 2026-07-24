"""Unit tests for the price oracle (no network — a stub source is injected)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.services.payments.onchain.assets import get_spec
from app.services.payments.onchain.oracle import PriceOracle, PriceUnavailable


async def test_stablecoin_is_pinned_and_never_calls_source() -> None:
    calls = {"n": 0}

    async def src(_cg: str) -> Decimal:
        calls["n"] += 1
        return Decimal("100")

    oracle = PriceOracle(source=src)
    quote = await oracle.quote(Decimal("10"), get_spec("USDT", "trc20"))
    assert quote.rate == Decimal(1)
    assert quote.crypto_amount == Decimal("10")
    assert calls["n"] == 0


async def test_volatile_priced_and_cached() -> None:
    calls = {"n": 0}

    async def src(_cg: str) -> Decimal:
        calls["n"] += 1
        return Decimal("100")

    oracle = PriceOracle(source=src, ttl_seconds=100)
    q1 = await oracle.quote(Decimal("10"), get_spec("BTC", "native"))
    q2 = await oracle.quote(Decimal("20"), get_spec("BTC", "native"))
    assert q1.rate == Decimal("100")
    assert q1.crypto_amount == Decimal("0.1")
    assert q2.crypto_amount == Decimal("0.2")
    assert calls["n"] == 1  # second call served from cache


async def test_non_positive_price_raises() -> None:
    async def bad(_cg: str) -> Decimal:
        return Decimal(0)

    oracle = PriceOracle(source=bad)
    with pytest.raises(PriceUnavailable):
        await oracle.usd_price(get_spec("ETH", "native"))
