"""Payment-provider webhook intake.

Verifies the signature on the RAW body, records the event (deduped), and applies it.
Processing runs inline here (fast: a few queries); the reconcile worker job is the
safety net if a webhook is missed. Swap to an ARQ enqueue if intake volume grows.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.core.errors import NotFound
from app.core.logging import log
from app.models import PaymentEvent
from app.services.payments.processing import ingest_webhook, process_payment_event
from app.services.payments.registry import get_payment_provider

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/payments/{provider}")
async def payments_webhook(provider: str, request: Request, session: DbSession) -> dict[str, bool]:
    prov = get_payment_provider()
    if prov.name != provider:
        raise NotFound("unknown provider")

    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not prov.verify_webhook(raw, headers):
        session.add(
            PaymentEvent(provider=provider, payload={"invalid": True}, signature_valid=False)
        )
        log.warning("payment.webhook.bad_signature", provider=provider)
        return {"ok": False}  # 200 — do not signal validity to an attacker

    dto = prov.parse_event(raw)
    event_id = await ingest_webhook(
        session, provider=provider, raw_body=raw, signature_valid=True, dto=dto
    )
    if event_id is not None:
        await process_payment_event(session, event_id)
    return {"ok": True}
