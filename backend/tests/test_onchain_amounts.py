"""Unit tests for on-chain amount uniquification + classification (no DB)."""

from __future__ import annotations

from decimal import Decimal

from app.services.payments.onchain.amounts import (
    absolute_tolerance,
    classify,
    expected_amount,
    unique_delta,
)
from app.services.payments.onchain.assets import SPECS, get_spec


def test_expected_amount_is_unique_and_deterministic() -> None:
    spec = get_spec("USDT", "trc20")  # quote_decimals = 4
    base = Decimal("10")
    a = expected_amount(base, spec, "order-A")
    b = expected_amount(base, spec, "order-B")
    assert a != b, "different orders must get different expected amounts"
    assert a == expected_amount(base, spec, "order-A"), "same order must be deterministic"


def test_delta_is_small_and_positive() -> None:
    spec = get_spec("USDT", "trc20")
    d = unique_delta("order-A", spec)
    assert Decimal(0) < d <= Decimal("0.0099")  # ≤ ~$0.01 for a stablecoin

    btc = get_spec("BTC", "native")  # quote_decimals = 8
    db = unique_delta("order-A", btc)
    assert Decimal(0) < db <= Decimal("0.00000099")


def test_expected_amount_within_one_cent_band_of_base() -> None:
    spec = get_spec("USDT", "trc20")
    e = expected_amount(Decimal("10"), spec, "order-A")
    assert Decimal("10") < e < Decimal("10.01")


def test_stablecoin_quotes_survive_an_exchange_withdrawal_form() -> None:
    """Every stablecoin amount we ask for must be typeable where the money actually is.

    Bybit's USDT withdrawal field takes four decimals. A six-decimal quote could not be
    sent from there at all: the customer typed what fitted, arrived a fraction short, and
    the payment fell out of the exact-match path into manual resolution. This asserts the
    property that prevents it — not the constant, the amount itself, at the precision it
    reaches the buyer.
    """
    for spec in SPECS.values():
        if not spec.is_stable:
            continue
        for order in ("order-A", "order-B", "order-Z", "1a2b3c"):
            amount = expected_amount(Decimal("23"), spec, order)
            assert -amount.as_tuple().exponent <= 4, f"{spec.key} quoted {amount}"


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
