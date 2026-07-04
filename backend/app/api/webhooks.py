"""Payment-provider webhook intake.

Verifies the signature on the RAW body, records the event (deduped), and applies it.
Processing runs inline here (fast: a few queries); the reconcile worker job is the
safety net if a webhook is missed. Swap to an ARQ enqueue if intake volume grows.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import DbSession
from app.core.errors import NotFound
from app.core.logging import log
from app.core.ratelimit import enforce
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
