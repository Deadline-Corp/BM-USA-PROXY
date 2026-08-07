"""Match an inbound on-chain transfer to the open invoice it pays for.

With a shared receiving address per rail, matching is by **amount** (each open invoice has
a unique expected amount) — or by **reference** on Solana. Ambiguity (two open invoices a
transfer could equally satisfy) resolves to *no match* so the deposit is parked for manual
review rather than credited to the wrong order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice
from app.services.payments.onchain.amounts import _quantum
from app.services.payments.onchain.assets import find_spec
from app.services.payments.onchain.chain_client import IncomingTransfer

_OPEN_STATUSES = ("pending", "confirming")

# How far above the quote a deposit may still settle an invoice. Buyers do round up, so a
# little slack is worth having — but only a little: every extra percent widens the window
# in which one order's money can settle a different order's invoice.
_OVERPAY_PCT = Decimal("0.02")  # 2%


def _overpay_cap(expected: Decimal) -> Decimal:
    return expected * _OVERPAY_PCT


@dataclass(frozen=True, slots=True)
class MatchResult:
    invoice: Invoice | None
    # exact | reference | nearest | no_open_invoice | ambiguous | unsupported
    # | exact_match_on_closed_invoice
    reason: str
    # The closed invoice this deposit exactly matches, when there is one. NOT a match —
    # nothing is credited — but it says whose money this is, which turns an anonymous
    # "unmatched" into "order #6 paid too late" for whoever has to sort it out.
    closed_invoice: Invoice | None = None


class PaymentMatcher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _base_query(self, transfer: IncomingTransfer) -> Select[tuple[Invoice]]:
        return select(Invoice).where(
            Invoice.provider == "onchain",
            Invoice.status.in_(_OPEN_STATUSES),
            Invoice.crypto_currency == transfer.asset,
            Invoice.crypto_network == transfer.network,
            Invoice.pay_address == transfer.to_address,
        )

    async def match(self, transfer: IncomingTransfer) -> MatchResult:
        spec = find_spec(transfer.asset, transfer.network)
        if spec is None:
            return MatchResult(None, "unsupported")

        # A Solana Pay reference is the strongest signal — try it first. It is issued per
        # invoice and derived from the order id, so a transaction carrying one names its
        # invoice outright rather than implying it from the amount. The amount is still
        # classified downstream: this says *whose* payment it is, not that it is enough.
        if transfer.reference_candidates:
            referenced = list(
                await self.session.scalars(
                    self._base_query(transfer).where(
                        Invoice.reference_pubkey.in_(transfer.reference_candidates)
                    )
                )
            )
            if len(referenced) == 1:
                return MatchResult(referenced[0], "reference")
            if len(referenced) > 1:
                # One transaction naming two of our open invoices is not something we can
                # split — park it rather than guess which order paid.
                return MatchResult(None, "ambiguous")

        q = _quantum(spec.quote_decimals)
        paid = transfer.amount.quantize(q)
        invoices = list(await self.session.scalars(self._base_query(transfer)))

        # exact amount match (the normal path — buyer pays the quoted amount verbatim)
        exact = [i for i in invoices if Decimal(str(i.crypto_amount)).quantize(q) == paid]
        if len(exact) == 1:
            return MatchResult(exact[0], "exact")
        if len(exact) > 1:
            return MatchResult(None, "ambiguous")

        # A deposit whose amount is the exact quote of an invoice that is no longer open
        # was plainly meant for THAT order. Two things depend on knowing that: the fuzzy
        # pass below must not spend it on somebody else's open invoice (production,
        # 2026-08-05 — a payment for an invoice that had expired 17s earlier closed the
        # next open one as an "overpayment"), and a late payment should be recorded as
        # such instead of as anonymous money.
        #
        # Checked BEFORE the "no open invoices at all" exit on purpose: when the buyer's
        # invoice is the only one there is and it has expired, that list is empty — and an
        # early return there is exactly the case this is meant to name.
        stale_exact = await self.session.scalar(
            select(Invoice).where(
                Invoice.provider == "onchain",
                Invoice.status.notin_(_OPEN_STATUSES),
                Invoice.crypto_currency == transfer.asset,
                Invoice.crypto_network == transfer.network,
                Invoice.pay_address == transfer.to_address,
                Invoice.crypto_amount == paid,
            )
        )
        if stale_exact is not None:
            return MatchResult(None, "exact_match_on_closed_invoice", closed_invoice=stale_exact)

        if not invoices:
            return MatchResult(None, "no_open_invoice")

        # nearest open invoice the amount could satisfy (over/slight-under), unambiguous only
        scored: list[tuple[Decimal, Invoice]] = []
        for inv in invoices:
            expected = Decimal(str(inv.crypto_amount))
            tol = Decimal(str(inv.amount_tolerance or 0))
            # Overpayment is bounded on purpose. `paid >= expected - tol` alone accepts an
            # overpayment of ANY size, which defeats the unique-amount design: a large
            # deposit would silently settle whichever small invoice happened to be open.
            # Anything past the cap goes to manual review instead of the wrong order.
            if paid > expected + _overpay_cap(expected):
                continue
            if paid >= expected - tol:  # covers overpayment and within-tolerance underpayment
                scored.append((abs(expected - paid), inv))
        if not scored:
            return MatchResult(None, "no_open_invoice")
        scored.sort(key=lambda t: t[0])
        if len(scored) >= 2 and scored[0][0] == scored[1][0]:
            return MatchResult(None, "ambiguous")
        return MatchResult(scored[0][1], "nearest")
