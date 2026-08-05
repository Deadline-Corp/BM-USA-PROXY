"""Generic, chain-agnostic watcher orchestration.

Given a ``ChainClient`` for one chain, each tick:

1. scans new blocks for inbound transfers to our watched addresses,
2. appends a ledger row per observed state (detected → confirming → …),
3. matches each transfer to an open invoice (by amount, or Solana reference),
4. once confirmations are deep enough, classifies the amount and drives activation
   through the same idempotent ``processing`` path every provider uses,
5. re-checks still-confirming deposits so stragglers finalize on a later tick.

The concrete per-chain ``ChainClient`` implementations arrive in later phases; this module
never changes when a new chain is added.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Invoice, Order
from app.models.onchain import ChainCursor, OnchainDepositLedger
from app.services.notifications import enqueue
from app.services.payments import processing
from app.services.payments.base import PaymentEventDTO
from app.services.payments.onchain.amounts import classify
from app.services.payments.onchain.chain_client import ChainClient, IncomingTransfer
from app.services.payments.onchain.clients import chain_rescan_overlap
from app.services.payments.onchain.config import OnchainConfig, get_onchain_config
from app.services.payments.onchain.ledger import LedgerWriter
from app.services.payments.onchain.matcher import PaymentMatcher

# a transfer in one of these ledger states is settled — don't reprocess it
_TERMINAL_LEDGER = frozenset(
    {"paid", "overpaid", "underpaid", "unmatched", "expired_deposit", "orphaned", "reorg_rollback"}
)

# safety bound on how many blocks one tick will scan (chain clients may lower this)
DEFAULT_MAX_BLOCKS = 500

# reorg re-validation looks at deposits finalized between MIN_AGE and WINDOW ago —
# skipping the just-finalized ones (which can't have reorged yet and whose fresh confs
# depth we already know), and stopping once they're too old for a reorg to matter.
_REVALIDATION_WINDOW_MINUTES = 30
_REVALIDATION_MIN_AGE_MINUTES = 1


@dataclass(slots=True)
class TickReport:
    chain: str
    from_block: int
    to_block: int
    head: int
    transfers: int
    finalized: int


def _transfer_from_ledger(row: OnchainDepositLedger) -> IncomingTransfer:
    return IncomingTransfer(
        chain=row.chain,
        asset=row.asset,
        network=row.network,
        txid=row.txid,
        to_address=row.to_address,
        amount=Decimal(str(row.amount)),
        log_index=row.log_index,
        from_address=row.from_address,
        block_number=row.block_number,
        block_time=row.block_time,
        confirmations=row.confirmations,
    )


async def _order_user_id(session: AsyncSession, order_id: int) -> int | None:
    user_id: int | None = await session.scalar(
        select(Order.user_id).where(Order.id == order_id)
    )
    return user_id


def _amount_usd(transfer: IncomingTransfer, invoice: Invoice) -> Decimal | None:
    rate = invoice.locked_rate
    if rate is None:
        return None
    return (transfer.amount * Decimal(str(rate))).quantize(Decimal("0.0001"))


async def _finalize(
    session: AsyncSession,
    transfer: IncomingTransfer,
    invoice: Invoice,
    confirmations: int,
    config: OnchainConfig,
    ledger: LedgerWriter,
) -> bool:
    """Confirmed deposit → classify amount, append ledger row, drive activation. Idempotent."""
    user_id = await _order_user_id(session, invoice.order_id)
    amount_usd = _amount_usd(transfer, invoice)
    classification = classify(
        transfer.amount,
        Decimal(str(invoice.crypto_amount)),
        Decimal(str(invoice.amount_tolerance or 0)),
    )
    deposit = await ledger.record_deposit(
        transfer,
        classification,  # paid | overpaid | underpaid
        invoice_id=invoice.id,
        user_id=user_id,
        confirmations=confirmations,
        amount_usd=amount_usd,
    )

    # emit through the shared idempotent path. paid_amount_usd is intentionally omitted:
    # our classify() is authoritative, and passing a rounded value could trip the
    # processing-layer short-amount recheck for a within-tolerance payment.
    emit_status = "underpaid" if classification == "underpaid" else "paid"
    prev_status = invoice.status
    payload = {
        "txid": transfer.txid,
        "log_index": transfer.log_index,
        "amount": str(transfer.amount),
        "amount_usd": str(amount_usd) if amount_usd is not None else None,
        "classification": classification,
        "confirmations": confirmations,
    }
    event_id = await processing.ingest_webhook(
        session,
        provider="onchain",
        raw_body=json.dumps(payload).encode(),
        signature_valid=True,
        dto=PaymentEventDTO(
            provider_invoice_id=invoice.provider_invoice_id,
            status=emit_status,
            # include chain+asset+network so two transfers sharing a txid but a
            # different asset (e.g. SOL + USDC in one Solana tx, or USDT + TRX in one
            # Tron tx, all log_index 0) don't collide on the dedupe key.
            provider_event_id=(
                f"{transfer.chain}:{transfer.asset}:{transfer.network}"
                f":{transfer.txid}:{transfer.log_index}"
            ),
        ),
    )
    if event_id is not None:
        result = await processing.process_payment_event(session, event_id)
        log.info(
            "onchain.finalize",
            chain=transfer.chain,
            invoice=invoice.id,
            classification=classification,
            result=result,
        )
    # invoice.status was moved by processing — log the true transition for the audit trail
    await ledger.record_invoice_status(
        invoice.id,
        from_status=prev_status,
        to_status=invoice.status,
        reason=f"{classification} via {transfer.txid}",
        deposit_ledger_id=deposit.id,
    )
    return True


async def process_transfer(
    session: AsyncSession,
    transfer: IncomingTransfer,
    *,
    config: OnchainConfig,
    ledger: LedgerWriter,
    matcher: PaymentMatcher,
) -> bool:
    """Ingest one observed transfer. Returns True if it reached a finalized state this call."""
    method = config.method(transfer.asset, transfer.network)
    if method is None:
        return False  # not a rail we watch

    latest = await ledger.latest_status(
        transfer.txid, transfer.log_index, asset=transfer.asset, network=transfer.network
    )
    if latest in _TERMINAL_LEDGER:
        return False  # already settled

    result = await matcher.match(transfer)
    invoice = result.invoice
    confs = transfer.confirmations

    if invoice is None:
        # first sighting → record it, then park as unmatched (no open invoice claims it)
        if latest is None:
            await ledger.record_deposit(transfer, "detected", confirmations=confs)
        await ledger.record_deposit(
            transfer, "unmatched", confirmations=confs, meta={"reason": result.reason}
        )
        log.warning(
            "onchain.unmatched",
            chain=transfer.chain,
            txid=transfer.txid,
            amount=str(transfer.amount),
            reason=result.reason,
        )
        return False

    user_id = await _order_user_id(session, invoice.order_id)
    amount_usd = _amount_usd(transfer, invoice)

    if latest is None:
        deposit = await ledger.record_deposit(
            transfer,
            "detected",
            invoice_id=invoice.id,
            user_id=user_id,
            confirmations=confs,
            amount_usd=amount_usd,
        )
        prev = invoice.status
        invoice.status = "confirming"
        invoice.matched_txid = transfer.txid
        invoice.matched_log_index = transfer.log_index
        invoice.confirmations = confs
        await ledger.record_invoice_status(
            invoice.id,
            from_status=prev,
            to_status="confirming",
            reason="deposit detected",
            deposit_ledger_id=deposit.id,
        )
    else:
        invoice.confirmations = confs

    if confs >= method.confirmations:
        return await _finalize(session, transfer, invoice, confs, config, ledger)

    # still shallow — append a confirming progress row and wait
    await ledger.record_deposit(
        transfer,
        "confirming",
        invoice_id=invoice.id,
        user_id=user_id,
        confirmations=confs,
        amount_usd=amount_usd,
    )
    # Tell the buyer we can see the money. Without this the screen sits on "waiting for
    # payment" from send until finality, which reads as "nothing happened". Sent from the
    # shallow branch only — a deposit that finalises on first sighting goes straight to
    # payment_received, so this never doubles up. dedupe_key keeps the 15s tick from
    # re-sending it on every pass.
    if user_id is not None:
        await enqueue(
            session,
            user_id=user_id,
            template_code="payment_detected",
            payload={"order_public_id": str(invoice.order_id)},
            dedupe_key=f"payment_detected:{invoice.id}",
        )
    return False


async def finalize_confirming(
    session: AsyncSession,
    client: ChainClient,
    config: OnchainConfig,
    ledger: LedgerWriter,
) -> int:
    """Re-check confirmation depth of still-confirming invoices and finalize the ready ones."""
    invoices = list(
        await session.scalars(
            select(Invoice).where(
                Invoice.provider == "onchain",
                Invoice.status == "confirming",
                Invoice.chain == client.chain,
                Invoice.matched_txid.isnot(None),
            )
        )
    )
    finalized = 0
    for invoice in invoices:
        method = config.method(invoice.crypto_currency or "", invoice.crypto_network or "")
        if method is None or invoice.matched_txid is None:
            continue
        confs = await client.confirmations(invoice.matched_txid)
        invoice.confirmations = confs
        if confs < method.confirmations:
            continue
        deposit = await ledger.latest_deposit(invoice.matched_txid, invoice.matched_log_index)
        if deposit is None:
            continue
        transfer = _transfer_from_ledger(deposit)
        try:
            async with session.begin_nested():
                done = await _finalize(session, transfer, invoice, confs, config, ledger)
            if done:
                finalized += 1
        except Exception:
            log.exception(
                "onchain.finalize_failed", chain=client.chain, invoice=invoice.id
            )
    return finalized


async def _get_cursor(session: AsyncSession, chain: str, head: int) -> ChainCursor:
    cursor = await session.get(ChainCursor, chain)
    if cursor is None:
        # start near the head on first run — do not backfill the entire chain history
        cursor = ChainCursor(chain=chain, last_scanned_block=max(0, head - 5))
        session.add(cursor)
        await session.flush()
    return cursor


async def revalidate_finalized(
    session: AsyncSession, client: ChainClient, ledger: LedgerWriter
) -> int:
    """Re-check recently-finalized deposits against the canonical chain (F8, reorg guard).

    If a deposit's tx is no longer canonical (confirmations dropped to 0) shortly after we
    finalized it, record a reorg_rollback row and route the order to manual_review + alert.
    We do NOT auto-revoke the access — a transient RPC miss must not punish a paying
    customer; the operator resolves. Only the recent post-finalization window is checked.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(minutes=_REVALIDATION_WINDOW_MINUTES)
    min_age = now - timedelta(minutes=_REVALIDATION_MIN_AGE_MINUTES)
    rows = list(
        await session.scalars(
            select(OnchainDepositLedger)
            .where(
                OnchainDepositLedger.chain == client.chain,
                OnchainDepositLedger.status.in_(("paid", "overpaid")),
                OnchainDepositLedger.created_at >= window_start,
                OnchainDepositLedger.created_at <= min_age,
            )
            .order_by(OnchainDepositLedger.created_at.desc())
        )
    )
    seen: set[tuple[str, int]] = set()
    reorged = 0
    for dep in rows:
        key = (dep.txid, dep.log_index)
        if key in seen:
            continue
        seen.add(key)
        latest = await ledger.latest_status(
            dep.txid, dep.log_index, asset=dep.asset, network=dep.network
        )
        if latest not in ("paid", "overpaid"):
            continue  # already superseded / rolled back
        if await client.confirmations(dep.txid) > 0:
            continue  # still canonical
        transfer = _transfer_from_ledger(dep)
        await ledger.record_deposit(
            transfer, "reorg_rollback", invoice_id=dep.invoice_id, user_id=dep.user_id,
            confirmations=0,
            amount_usd=Decimal(str(dep.amount_usd)) if dep.amount_usd is not None else None,
            meta={"reason": "tx no longer canonical after finalization"},
        )
        if dep.invoice_id is not None:
            invoice = await session.get(Invoice, dep.invoice_id)
            if invoice is not None:
                order = await session.get(Order, invoice.order_id)
                if order is not None and order.status != "manual_review":
                    order.status = "manual_review"
        log.error(
            "onchain.reorg_suspected", chain=client.chain, txid=dep.txid, invoice=dep.invoice_id
        )
        reorged += 1
    return reorged


async def run_chain_tick(
    session: AsyncSession,
    client: ChainClient,
    *,
    config: OnchainConfig | None = None,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> TickReport:
    """One watcher pass for a single chain. Safe to call on a cron; advances the cursor."""
    config = config or get_onchain_config()
    ledger = LedgerWriter(session)
    matcher = PaymentMatcher(session)
    methods = config.methods_for_chain(client.chain)

    head = await client.get_block_height()
    cursor = await _get_cursor(session, client.chain, head)
    # Start behind the cursor, not at it: a transfer the API had not indexed yet when its
    # window was scanned would otherwise sit in a span nothing ever looks at again.
    # Re-processing is a no-op once a deposit reaches a terminal ledger status.
    overlap = chain_rescan_overlap(client.chain)
    from_block = max(0, cursor.last_scanned_block + 1 - overlap)

    transfers: list[IncomingTransfer] = []
    to_block = cursor.last_scanned_block
    if methods and head >= from_block:
        to_block = min(head, from_block + max_blocks - 1)
        transfers = await client.scan(from_block=from_block, to_block=to_block, methods=methods)
        for transfer in transfers:
            # SAVEPOINT per transfer: one poisoned deposit (e.g. an IntegrityError
            # deep in activation) must not roll back the cursor + every other transfer
            # in this tick and wedge the chain forever. Isolate and carry on.
            try:
                async with session.begin_nested():
                    await process_transfer(
                        session, transfer, config=config, ledger=ledger, matcher=matcher
                    )
            except Exception:
                log.exception(
                    "onchain.transfer_failed", chain=client.chain, txid=transfer.txid
                )
        cursor.last_scanned_block = to_block
        cursor.updated_at = datetime.now(UTC)

    finalized = await finalize_confirming(session, client, config, ledger)
    await revalidate_finalized(session, client, ledger)
    return TickReport(
        chain=client.chain,
        from_block=from_block,
        to_block=to_block,
        head=head,
        transfers=len(transfers),
        finalized=finalized,
    )
