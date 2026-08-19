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

# Distinct uniquification buckets — the delta occupies the last TWO quote-decimals.
#
# Three digits' worth would be ~$0.10 on a stablecoin now that stablecoins quote to four
# decimals (see assets.py): a tenth of a percent of a $85 order, but ten times what it used
# to be, and visible on a screen that says "send exactly this". Two digits keeps the nudge
# under a cent. Fewer buckets means invoices collide more often, which costs nothing —
# _ensure_unique_crypto_amount walks the amount up by one step until it is free, and the
# partial-unique index is the hard backstop behind that.
_DELTA_BUCKETS = 99

Classification = Literal["paid", "overpaid", "underpaid"]


def _quantum(decimals: int) -> Decimal:
    """The smallest representable step at ``decimals`` places, e.g. 6 → Decimal('0.000001')."""
    return Decimal(1).scaleb(-decimals)


def unique_delta(order_public_id: str, spec: AssetSpec) -> Decimal:
    """A small, deterministic, per-order amount added to make the expected amount unique.

    Ranges over ``[1, 99] * 10**-quote_decimals`` — at most the last two quote decimals,
    which is ≤ ~$0.01 for stablecoins and negligible for high-decimal volatile assets.
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

    On the ``"underpaid"`` branch being unreachable today, and staying anyway: the matcher
    admits a candidate only when ``paid >= expected - tolerance`` (matcher.py), so anything
    short beyond tolerance never reaches this function — it is parked as ``unmatched``
    instead, and no production deposit has ever carried the ``underpaid`` status.

    The branch is not dead weight, it is the backstop for that invariant. Whoever later
    widens the matcher — accepting short payments for manual review, say — would otherwise
    have this function silently call an underpayment ``"paid"`` and hand out the access.
    Deleting a correct branch because today's only caller cannot reach it is exactly how
    that bug gets built. Keep both: the pre-filter for behaviour, this for truth.
    """
    if paid > expected:
        return "overpaid"
    if paid == expected:
        return "paid"
    if paid >= expected - tolerance:
        return "paid"
    return "underpaid"
