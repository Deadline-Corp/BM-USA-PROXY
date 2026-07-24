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


@dataclass(frozen=True, slots=True)
class MatchResult:
    invoice: Invoice | None
    reason: str  # exact | reference | nearest | no_open_invoice | ambiguous | unsupported


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

        # Solana Pay reference is the strongest signal — try it first.
        if transfer.reference:
            inv = await self.session.scalar(
                self._base_query(transfer).where(
                    Invoice.reference_pubkey == transfer.reference
                )
            )
            if inv is not None:
                return MatchResult(inv, "reference")

        invoices = list(await self.session.scalars(self._base_query(transfer)))
        if not invoices:
            return MatchResult(None, "no_open_invoice")

        q = _quantum(spec.quote_decimals)
        paid = transfer.amount.quantize(q)

        # exact amount match (the normal path — buyer pays the quoted amount verbatim)
        exact = [i for i in invoices if Decimal(str(i.crypto_amount)).quantize(q) == paid]
        if len(exact) == 1:
            return MatchResult(exact[0], "exact")
        if len(exact) > 1:
            return MatchResult(None, "ambiguous")

        # nearest open invoice the amount could satisfy (over/slight-under), unambiguous only
        scored: list[tuple[Decimal, Invoice]] = []
        for inv in invoices:
            expected = Decimal(str(inv.crypto_amount))
            tol = Decimal(str(inv.amount_tolerance or 0))
            if paid >= expected - tol:  # covers overpayment and within-tolerance underpayment
                scored.append((abs(expected - paid), inv))
        if not scored:
            return MatchResult(None, "no_open_invoice")
        scored.sort(key=lambda t: t[0])
        if len(scored) >= 2 and scored[0][0] == scored[1][0]:
            return MatchResult(None, "ambiguous")
        return MatchResult(scored[0][1], "nearest")
