"""Unit tests for on-chain amount uniquification + classification (no DB)."""

from __future__ import annotations

from decimal import Decimal

from app.services.payments.onchain.amounts import (
    absolute_tolerance,
    classify,
    expected_amount,
    unique_delta,
)
from app.services.payments.onchain.assets import get_spec


def test_expected_amount_is_unique_and_deterministic() -> None:
    spec = get_spec("USDT", "trc20")  # quote_decimals = 6
    base = Decimal("10")
    a = expected_amount(base, spec, "order-A")
    b = expected_amount(base, spec, "order-B")
    assert a != b, "different orders must get different expected amounts"
    assert a == expected_amount(base, spec, "order-A"), "same order must be deterministic"


def test_delta_is_small_and_positive() -> None:
    spec = get_spec("USDT", "trc20")
    d = unique_delta("order-A", spec)
    assert Decimal(0) < d <= Decimal("0.000999")  # ≤ ~$0.001 for a stablecoin

    btc = get_spec("BTC", "native")  # quote_decimals = 8
    db = unique_delta("order-A", btc)
    assert Decimal(0) < db <= Decimal("0.00000999")


def test_expected_amount_within_one_cent_band_of_base() -> None:
    spec = get_spec("USDT", "trc20")
    e = expected_amount(Decimal("10"), spec, "order-A")
    assert Decimal("10") < e < Decimal("10.001")


def test_classify_paid_over_under() -> None:
    exp = Decimal("10.000500")
    assert classify(exp, exp, Decimal(0)) == "paid"
    assert classify(Decimal("10.000600"), exp, Decimal(0)) == "overpaid"
    assert classify(Decimal("10.000400"), exp, Decimal(0)) == "underpaid"


def test_classify_within_tolerance_is_paid() -> None:
    exp = Decimal("10.000500")
    # 10.000490 is 0.00001 short, tolerance 0.00002 → still paid
    assert classify(Decimal("10.000490"), exp, Decimal("0.00002")) == "paid"
    # 10.000470 is 0.00003 short, beyond tolerance → underpaid
    assert classify(Decimal("10.000470"), exp, Decimal("0.00002")) == "underpaid"


def test_absolute_tolerance() -> None:
    assert absolute_tolerance(Decimal("100"), Decimal("0.5")) == Decimal("0.5")
    assert absolute_tolerance(Decimal("100"), Decimal("0")) == Decimal(0)
    assert absolute_tolerance(Decimal("100"), Decimal("-1")) == Decimal(0)
