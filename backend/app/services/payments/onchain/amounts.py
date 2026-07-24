"""Deterministic amount uniquification + payment classification.

With a single shared receiving address per rail, the *amount* is the routing key: every
open invoice on a rail is given a slightly different expected amount so an incoming
transfer maps to exactly one invoice. The delta is derived deterministically from the
order id (no DB round-trip needed at invoice-creation time) and is small in USD terms.

Matching is primarily **exact** — the buyer pays the quoted amount verbatim. ``classify``
additionally tolerates a configurable underpayment band and flags over/underpayment.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from app.services.payments.onchain.assets import AssetSpec

# distinct uniquification buckets (delta occupies the last 3 quote-decimals)
_DELTA_BUCKETS = 999

Classification = Literal["paid", "overpaid", "underpaid"]


def _quantum(decimals: int) -> Decimal:
    """The smallest representable step at ``decimals`` places, e.g. 6 → Decimal('0.000001')."""
    return Decimal(1).scaleb(-decimals)


def unique_delta(order_public_id: str, spec: AssetSpec) -> Decimal:
    """A small, deterministic, per-order amount added to make the expected amount unique.

    Ranges over ``[1, 999] * 10**-quote_decimals`` — at most the last three quote decimals,
    which is ≤ ~$0.001 for stablecoins and negligible for high-decimal volatile assets.
    """
    digest = hashlib.sha256(order_public_id.encode("utf-8")).digest()
    bucket = 1 + (int.from_bytes(digest[:8], "big") % _DELTA_BUCKETS)
    return _quantum(spec.quote_decimals) * bucket


def expected_amount(base_amount: Decimal, spec: AssetSpec, order_public_id: str) -> Decimal:
    """Quote precision amount the buyer must send: rounded base + unique delta."""
    q = _quantum(spec.quote_decimals)
    rounded = base_amount.quantize(q, rounding=ROUND_DOWN)
    return (rounded + unique_delta(order_public_id, spec)).quantize(q)


def absolute_tolerance(expected: Decimal, tolerance_pct: Decimal) -> Decimal:
    """Absolute underpayment band from a percentage (``tolerance_pct`` of 0.5 == 0.5%)."""
    if tolerance_pct <= 0:
        return Decimal(0)
    return expected * tolerance_pct / Decimal(100)


def classify(paid: Decimal, expected: Decimal, tolerance: Decimal) -> Classification:
    """Classify a received amount against the expected amount.

    ``tolerance`` is the absolute underpayment we still accept as fully paid.
    """
    if paid > expected:
        return "overpaid"
    if paid == expected:
        return "paid"
    if paid >= expected - tolerance:
        return "paid"
    return "underpaid"
