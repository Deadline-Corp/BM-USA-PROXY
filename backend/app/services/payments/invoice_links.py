"""Turn an invoice into the links a buyer can act on: a wallet deep link, and a QR payload.

Both the checkout screen and the public `/pay/{order}` hand-off need the same URI built
the same way, including the per-rail testnet contract override — so it lives here rather
than in whichever router happened to need it first.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import Invoice
from app.services.payments.onchain.assets import find_spec
from app.services.payments.onchain.config import get_onchain_config
from app.services.payments.onchain.payment_uri import build_payment_uri


def invoice_pay_uri(inv: Invoice) -> str | None:
    """The wallet deep link for this invoice, or ``None`` when the chain has no standard.

    ``None`` is a real answer, not a failure: Tron has no URI scheme the major wallets
    honour, so there is nothing to open and callers must fall back to the bare address.
    """
    if not inv.pay_address or inv.crypto_amount is None:
        return None
    if not inv.crypto_currency or not inv.crypto_network:
        return None
    spec = find_spec(inv.crypto_currency, inv.crypto_network)
    if spec is None:
        return None
    try:
        cfg = get_onchain_config()
        # a per-rail override (testnet contract) changes the token in the deep link
        method = cfg.method(inv.crypto_currency, inv.crypto_network)
        return build_payment_uri(
            spec=method.spec if method else spec,
            to_address=inv.pay_address,
            amount=Decimal(str(inv.crypto_amount)),
            network=cfg.network,
            # Solana only. Carrying it lets the watcher recognise the invoice from the
            # transaction itself instead of matching on the amount alone.
            reference=inv.reference_pubkey,
        )
    except Exception:  # config not loaded / malformed — the address alone still works
        return None


def invoice_qr_payload(inv: Invoice) -> str | None:
    """What to encode in the checkout QR: the deep link if there is one, else the address."""
    return invoice_pay_uri(inv) or inv.pay_address
