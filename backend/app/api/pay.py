"""Public wallet hand-off: ``/pay/{order_public_id}`` redirects to the wallet deep link.

A mini app cannot navigate to ``ethereum:`` from inside the Telegram client — the Android
WebView answers ERR_UNKNOWN_URL_SCHEME and takes the page down with it. What it *can* do
is ask Telegram to open an ``https`` URL in the real browser, and the real browser hands
unknown schemes to the OS, which is what raises the "choose a wallet" sheet. So the
checkout button opens this URL and this URL redirects into the scheme.

Deliberately unauthenticated: it is opened in an external browser that has no Telegram
initData to present. The order id is a random UUID, and what the redirect discloses — our
receiving address and the amount — is already on the buyer's own screen. The redirect
target is constructed from our own configuration and never from a query parameter, so
this cannot be turned into an open redirect.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import Invoice, Order
from app.services.payments.invoice_links import invoice_pay_uri

router = APIRouter(tags=["pay"])

# Statuses where sending money still settles this invoice. Redirecting outside them would
# invite a deposit the watcher has no open invoice to match — money parked pending a human.
_OPEN = ("pending", "confirming")


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    """A plain, self-contained page. A person sees this, so it must not be a JSON error."""
    return HTMLResponse(
        status_code=status_code,
        content=(
            "<!doctype html><meta charset=utf-8>"
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>{title}</title>"
            "<style>body{font:16px/1.5 system-ui,sans-serif;margin:0;min-height:100dvh;"
            "display:grid;place-items:center;padding:24px;color:#1b2330;background:#f6f8fb}"
            "div{max-width:22rem;text-align:center}h1{font-size:1.1rem;margin:0 0 .5rem}"
            "p{margin:0;color:#5b6675}</style>"
            f"<div><h1>{title}</h1><p>{body}</p></div>"
        ),
    )


@router.get("/pay/{order_public_id}", include_in_schema=False)
async def open_in_wallet(order_public_id: str, session: DbSession) -> Response:
    try:
        public_id = uuid.UUID(order_public_id)
    except ValueError:
        return _page("Link not valid", "This payment link is malformed.", 404)

    invoice = await session.scalar(
        select(Invoice)
        .join(Order, Order.id == Invoice.order_id)
        .where(Order.public_id == public_id)
        .order_by(Invoice.id.desc())
        .limit(1)
    )
    if invoice is None:
        return _page("Order not found", "This payment link no longer points anywhere.", 404)
    if invoice.status not in _OPEN:
        return _page(
            "Invoice is closed",
            "This invoice is no longer awaiting payment. Open the app and start a new order.",
        )

    uri = invoice_pay_uri(invoice)
    if uri is None:
        return _page(
            "No wallet link for this coin",
            "This network has no wallet link standard — copy the address and amount from "
            "the app instead.",
        )
    return RedirectResponse(url=uri, status_code=302)
