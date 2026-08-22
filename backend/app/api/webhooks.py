"""Payment-provider webhook intake.

Verifies the signature on the RAW body, records the event (deduped), and applies it.
Processing runs inline here (fast: a few queries); the reconcile worker job is the
safety net if a webhook is missed. Swap to an ARQ enqueue if intake volume grows.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import DbSession
from app.core.errors import NotFound
from app.core.logging import log
from app.core.ratelimit import enforce
from app.services.payments.onchain import webhooks as onchain_webhooks
from app.services.payments.processing import ingest_webhook, process_payment_event
from app.services.payments.registry import get_payment_provider

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_MAX_WEBHOOK_BYTES = 64 * 1024


@router.post("/payments/{provider}", response_model=None)
async def payments_webhook(
    provider: str, request: Request, session: DbSession
) -> JSONResponse | dict[str, bool]:
    prov = get_payment_provider()
    if prov.name != provider:
        raise NotFound("unknown provider")

    # Rate-limit per provider to blunt webhook flooding / DoS.
    await enforce(f"webhook:{provider}", limit=60, window_sec=60)

    # Reject oversized bodies early — do not read unbounded payloads into memory.
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            size = int(cl)
        except ValueError:
            return {"ok": False}
        if size > _MAX_WEBHOOK_BYTES:
            return JSONResponse({"ok": False}, status_code=413)

    raw = await request.body()
    if len(raw) > _MAX_WEBHOOK_BYTES:  # defensive: Content-Length may be missing/wrong
        return JSONResponse({"ok": False}, status_code=413)

    headers = {k.lower(): v for k, v in request.headers.items()}
    if not prov.verify_webhook(raw, headers):
        # Do NOT persist invalid-signature events — they would flood the table.
        # Just log and return 200 so an attacker learns nothing about validity.
        log.warning("payment.webhook.bad_signature", provider=provider, body_len=len(raw))
        return {"ok": False}

    dto = prov.parse_event(raw)
    event_id = await ingest_webhook(
        session, provider=provider, raw_body=raw, signature_valid=True, dto=dto
    )
    if event_id is not None:
        await process_payment_event(session, event_id)
    return {"ok": True}


@router.post("/alchemy", response_model=None)
async def alchemy_activity(request: Request) -> JSONResponse | dict[str, bool]:
    """One of our receiving addresses was touched — go and look at that chain.

    Deliberately does nothing with the contents. The body carries a float amount and can be
    replayed; a signature proves only that the delivery is ours, not that the money is
    final or worth what it says. So this marks the chain and the watcher reads the chain,
    keeping every rule about confirmations, exact amounts and idempotency in the one place
    that already has them.

    Always 200 on a well-formed request, including an unknown network: Alchemy retries
    anything else, and a retry storm over a delivery we would ignore anyway helps nobody.
    """
    await enforce("webhook:alchemy", limit=240, window_sec=60)

    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            size = int(cl)
        except ValueError:
            return {"ok": False}
        if size > _MAX_WEBHOOK_BYTES:
            return JSONResponse({"ok": False}, status_code=413)

    raw = await request.body()
    if len(raw) > _MAX_WEBHOOK_BYTES:
        return JSONResponse({"ok": False}, status_code=413)

    if not onchain_webhooks.verify(raw, request.headers.get("x-alchemy-signature")):
        # Same posture as the payment webhook above: log, keep nothing, and answer the
        # same way as for a valid one so an attacker learns nothing about validity.
        log.warning("onchain.webhook.bad_signature", body_len=len(raw))
        return {"ok": False}

    try:
        payload = json.loads(raw)
    except ValueError:
        log.warning("onchain.webhook.unparsable")
        return {"ok": False}

    chain = onchain_webhooks.chain_of(payload)
    if chain is None:
        log.warning("onchain.webhook.unknown_network", payload_fields=sorted(payload)[:5])
        return {"ok": True}

    await onchain_webhooks.ring(chain)
    log.info("onchain.webhook.received", chain=chain)
    return {"ok": True}
