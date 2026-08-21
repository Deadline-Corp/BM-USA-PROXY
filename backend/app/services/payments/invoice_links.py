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


def invoice_qr_code(inv: Invoice) -> str | None:
    """The QR payload, carrying the amount only where doing so is safe to scan anywhere.

    A QR is scanned from a second device, and that device is usually an exchange app. An
    exchange reads a withdrawal QR as an address: it takes the text after the scheme and
    stops. On most rails that is exactly the recipient, so the amount rides along in the
    query string and both a wallet and an exchange get what they need from one code.

    EIP-681 token payments are the exception, and not for convenience. A token payment is a
    contract call, so the address after ``ethereum:`` is the TOKEN CONTRACT and the
    recipient is a parameter. Bybit refusing that code outright — which is what the client's
    operator hit — is the safe behaviour; an app that parsed it the naive way would send the
    customer's USDT to the USDT contract, where it is gone for good. So those rails get the
    bare address and the buyer types the amount printed beside it.

    The rule is read off the URI rather than kept as a list of chains, so a rail added to
    `build_payment_uri` later is judged by the same test instead of by somebody remembering
    this comment.
    """
    address = inv.pay_address
    uri = invoice_pay_uri(inv)
    if not uri or not address:
        return address
    scheme, _, rest = uri.partition(":")
    if not scheme:
        return address
    # What a scanner that only understands addresses would come away with.
    leading = rest.split("?", 1)[0].split("@", 1)[0].split("/", 1)[0]
    return uri if leading.lower() == address.lower() else address
