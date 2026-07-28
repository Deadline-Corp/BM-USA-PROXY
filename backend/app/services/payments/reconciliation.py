"""Daily payment reconciliation.

Answers one operational question every day: "did we miss a payment, or credit one we
shouldn't have?" It cross-checks the order/invoice state against the append-only on-chain
deposit ledger and surfaces four discrepancy classes an operator must look at:

* unmatched_deposits   — money landed on a receiving address but matched no open invoice
                         (the classic "missed payment"): the customer paid, we didn't credit.
* paid_without_ledger  — an on-chain invoice is 'paid' but no confirmed ledger row backs it
                         (credited without on-chain proof — a bug or a manual override).
* stuck_confirming     — a deposit was detected but the invoice never finalized (wedged).
* paid_not_provisioned — the order was paid but access was never delivered.

A day with an empty discrepancy set is a clean settlement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice, Order
from app.models.onchain import OnchainDepositLedger

# how long a 'confirming' invoice may sit before it is flagged as wedged
_STUCK_CONFIRMING_HOURS = 3

# latest ledger row per transfer = its current state (same logic as the v_deposit_current
# view, inlined so this works against a create_all() test DB that has no views).
_CURRENT = (
    "SELECT DISTINCT ON (txid, log_index) * FROM onchain_deposit_ledger "
    "ORDER BY txid, log_index, created_at DESC, id DESC"
)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def reconcile_day(session: AsyncSession, day: date) -> dict[str, Any]:
    start, end = _day_bounds(day)

    # ── settled totals ─────────────────────────────────────────────────────
    paid_row = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Invoice.amount_usd), 0)).where(
                Invoice.status == "paid",
                Invoice.paid_at >= start,
                Invoice.paid_at < end,
            )
        )
    ).one()
    paid_count, paid_sum = int(paid_row[0]), Decimal(str(paid_row[1]))

    # deposits observed that day, by their CURRENT state (latest ledger row per transfer)
    deposits_by_status: dict[str, int] = {}
    rows = await session.execute(
        text(
            f"SELECT status, count(*) FROM ({_CURRENT}) cur "  # noqa: S608 (_CURRENT is a constant)
            "WHERE observed_at >= :start AND observed_at < :end GROUP BY status"
        ),
        {"start": start, "end": end},
    )
    for status, count in rows:
        deposits_by_status[status] = int(count)

    # ── discrepancies ──────────────────────────────────────────────────────
    unmatched = list(
        await session.execute(
            text(
                "SELECT txid, chain, asset, amount, amount_usd, to_address "  # noqa: S608
                f"FROM ({_CURRENT}) cur WHERE status = 'unmatched' "
                "AND observed_at >= :start AND observed_at < :end ORDER BY observed_at"
            ),
            {"start": start, "end": end},
        )
    )
    unmatched_deposits = [
        {
            "txid": r[0], "chain": r[1], "asset": r[2],
            "amount": str(r[3]), "amount_usd": float(r[4]) if r[4] is not None else None,
            "to_address": r[5],
        }
        for r in unmatched
    ]

    # on-chain invoices marked paid today with NO confirmed ledger row behind them
    onchain_paid = list(
        await session.scalars(
            select(Invoice).where(
                Invoice.provider == "onchain",
                Invoice.status == "paid",
                Invoice.paid_at >= start,
                Invoice.paid_at < end,
            )
        )
    )
    paid_without_ledger = []
    for inv in onchain_paid:
        backed = await session.scalar(
            select(func.count())
            .select_from(OnchainDepositLedger)
            .where(
                OnchainDepositLedger.invoice_id == inv.id,
                OnchainDepositLedger.status.in_(("paid", "overpaid")),
            )
        )
        if not backed:
            paid_without_ledger.append(
                {"invoice_id": str(inv.id), "order_id": str(inv.order_id),
                 "amount_usd": float(inv.amount_usd), "matched_txid": inv.matched_txid}
            )

    # deposits detected but the invoice never finalized (ongoing health, not date-scoped)
    stuck_cutoff = datetime.now(UTC) - timedelta(hours=_STUCK_CONFIRMING_HOURS)
    stuck = list(
        await session.scalars(
            select(Invoice).where(
                Invoice.status == "confirming",
                Invoice.matched_txid.isnot(None),
                Invoice.updated_at < stuck_cutoff,
            )
        )
    )
    stuck_confirming = [
        {"invoice_id": str(i.id), "matched_txid": i.matched_txid,
         "confirmations": i.confirmations, "chain": i.chain}
        for i in stuck
    ]

    # orders paid today but access never delivered
    not_provisioned = list(
        await session.scalars(
            select(Order).where(
                Order.status.in_(("paid", "provisioning", "manual_review")),
                Order.paid_at >= start,
                Order.paid_at < end,
            )
        )
    )
    paid_not_provisioned = [
        {"order_id": str(o.public_id), "status": o.status, "amount_usd": float(o.amount_usd)}
        for o in not_provisioned
    ]

    discrepancies = {
        "unmatched_deposits": unmatched_deposits,
        "paid_without_ledger": paid_without_ledger,
        "stuck_confirming": stuck_confirming,
        "paid_not_provisioned": paid_not_provisioned,
    }
    total_issues = sum(len(v) for v in discrepancies.values())
    return {
        "date": day.isoformat(),
        "paid": {"count": paid_count, "amount_usd": float(paid_sum)},
        "deposits_by_status": deposits_by_status,
        "discrepancies": discrepancies,
        "issue_count": total_issues,
        "clean": total_issues == 0,
    }
