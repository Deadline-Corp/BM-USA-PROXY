"""Operator resolution of deposits the watcher could not place itself.

A shared receiving address means some money will always land that no rule can safely
attribute: an invoice that expired seconds before the transfer was seen, a buyer who sent
a round number, a payment for an order created on another device. The watcher deliberately
parks those as ``unmatched`` rather than guessing — guessing is how one buyer's money ends
up settling another's invoice.

Parking them is only half a system, though. Until this module existed the ledger showed
the stuck deposit and offered nothing to do about it, so the money simply sat there.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.logging import log
from app.models import Invoice, Order
from app.models.onchain import OnchainDepositLedger
from app.services.payments import processing
from app.services.payments.base import PaymentEventDTO
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.ledger import LedgerWriter

# States where the deposit is still waiting for a human decision.
_RESOLVABLE = ("unmatched", "underpaid", "expired_deposit", "orphaned")
# States that already settled — re-resolving would double-credit.
_SETTLED = ("paid", "matched", "overpaid")


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _latest_row(session: AsyncSession, deposit_id: int) -> OnchainDepositLedger:
    """The deposit's current state — the newest row for its (txid, log_index)."""
    anchor = await session.get(OnchainDepositLedger, deposit_id)
    if anchor is None:
        raise NotFound("deposit not found")
    latest = await session.scalar(
        select(OnchainDepositLedger)
        .where(
            OnchainDepositLedger.txid == anchor.txid,
            OnchainDepositLedger.log_index == anchor.log_index,
        )
        .order_by(OnchainDepositLedger.id.desc())
        .limit(1)
    )
    return latest or anchor


def _as_transfer(row: OnchainDepositLedger) -> IncomingTransfer:
    return IncomingTransfer(
        chain=row.chain,
        asset=row.asset,
        network=row.network,
        txid=row.txid,
        to_address=row.to_address or "",
        amount=Decimal(str(row.amount)),
        from_address=row.from_address,
        block_time=row.block_time,
        confirmations=row.confirmations or 0,
        log_index=row.log_index,
        block_number=row.block_number,
    )


async def _find_order(session: AsyncSession, reference: str) -> Order | None:
    """The order behind whatever the operator pasted: its number or its id.

    The console shows orders as `#412` everywhere, so `#412` is what gets pasted here. The
    id is still accepted because the candidate list and older notes carry it, and because
    it is what the customer's own payment link is built from.
    """
    reference = reference.strip()
    number = reference.lstrip("#")
    found: Order | None
    if number.isdigit():
        found = await session.scalar(select(Order).where(Order.id == int(number)))
        return found
    try:
        uuid.UUID(reference)
    except ValueError:
        return None  # neither a number nor an id — nothing to look up
    found = await session.scalar(select(Order).where(Order.public_id == reference))
    return found


async def attach_to_order(
    session: AsyncSession,
    *,
    deposit_id: int,
    order_public_id: str,
    operator_id: int,
    note: str | None = None,
) -> dict:
    """Credit a parked deposit to an order and let the normal paid path take over.

    Routed through ``processing.ingest_webhook`` rather than flipping statuses by hand, so
    a manual attach provisions, notifies and dedupes exactly like an automatic one. The
    amount is NOT re-classified: the operator has looked at it and decided it settles this
    order, which is the entire point of the override.
    """
    row = await _latest_row(session, deposit_id)
    if row.status in _SETTLED:
        raise Conflict(f"deposit already settled ({row.status})")
    if row.status not in _RESOLVABLE:
        raise Conflict(f"deposit is in state '{row.status}' and needs no resolution")

    order = await _find_order(session, order_public_id)
    if order is None:
        raise NotFound("order not found")
    invoice = await session.scalar(select(Invoice).where(Invoice.order_id == order.id))
    if invoice is None:
        raise NotFound("that order has no invoice")
    if invoice.status == "paid":
        raise Conflict("that order is already paid")

    ledger = LedgerWriter(session)
    transfer = _as_transfer(row)
    meta = {
        "resolution": "manual_attach",
        "operator_id": operator_id,
        "previous_status": row.status,
        "note": note,
    }
    await ledger.record_deposit(
        transfer,
        "matched",
        invoice_id=invoice.id,
        user_id=order.user_id,
        amount_usd=Decimal(str(row.amount_usd)) if row.amount_usd is not None else None,
        meta=meta,
    )
    await ledger.record_deposit(
        transfer,
        "paid",
        invoice_id=invoice.id,
        user_id=order.user_id,
        amount_usd=Decimal(str(row.amount_usd)) if row.amount_usd is not None else None,
        meta=meta,
    )
    invoice.matched_txid = row.txid
    invoice.matched_log_index = row.log_index

    payload = {
        "txid": row.txid,
        "log_index": row.log_index,
        "amount": str(row.amount),
        "manual": True,
        "operator_id": operator_id,
    }
    prev_status = invoice.status
    event_id = await processing.ingest_webhook(
        session,
        provider="onchain",
        raw_body=json.dumps(payload).encode(),
        signature_valid=True,
        dto=PaymentEventDTO(
            provider_invoice_id=invoice.provider_invoice_id,
            status="paid",
            # Stable and manual-specific: a double-click, or an operator retrying after a
            # timeout, must not credit the order twice.
            provider_event_id=f"manual:{row.txid}:{row.log_index}",
        ),
    )
    # ingest_webhook only *records* the event — applying it is a second, separate call.
    result = "duplicate_event" if event_id is None else await processing.process_payment_event(
        session, event_id
    )
    await ledger.record_invoice_status(
        invoice.id,
        from_status=prev_status,
        to_status=invoice.status,
        reason=f"manual attach by operator {operator_id}",
    )
    log.info(
        "onchain.manual_attach",
        deposit=deposit_id, txid=row.txid, invoice=invoice.id,
        order=str(order.public_id), operator=operator_id, result=result,
    )
    return {"deposit_id": deposit_id, "invoice_id": invoice.id, "order_public_id": order_public_id}


async def write_off(
    session: AsyncSession, *, deposit_id: int, operator_id: int, reason: str
) -> dict:
    """Close a parked deposit without crediting anyone (refunded off-platform, dust, …).

    Append-only like everything else here: the deposit is not deleted or edited, a closing
    row is added on top so the original observation and the decision both stay on record.
    """
    row = await _latest_row(session, deposit_id)
    if row.status in _SETTLED:
        raise Conflict(f"deposit already settled ({row.status})")

    await LedgerWriter(session).record_deposit(
        _as_transfer(row),
        "orphaned",
        invoice_id=row.invoice_id,
        user_id=row.user_id,
        amount_usd=Decimal(str(row.amount_usd)) if row.amount_usd is not None else None,
        meta={
            "resolution": "written_off",
            "operator_id": operator_id,
            "previous_status": row.status,
            "reason": reason,
        },
    )
    log.info(
        "onchain.manual_write_off",
        deposit=deposit_id, txid=row.txid, operator=operator_id, reason=reason,
    )
    return {"deposit_id": deposit_id, "status": "orphaned"}
