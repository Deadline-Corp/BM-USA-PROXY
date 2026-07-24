"""PaymentProvider interface + DTOs. One interface, swappable adapters (DG-1).

Invariant #1 (payment idempotency) lives above this layer: 1 paid event = 1 activation,
guarded by UNIQUE(provider, provider_invoice_id) and the payment_events dedupe index.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(slots=True)
class InvoiceDTO:
    provider_invoice_id: str
    payment_url: str | None
    pay_address: str | None
    crypto_currency: str | None
    crypto_network: str | None
    crypto_amount: Decimal | None
    expires_at_epoch: int
    # on-chain provider extras (None for hosted processors)
    chain: str | None = None
    base_amount: Decimal | None = None
    amount_tolerance: Decimal | None = None
    locked_rate: Decimal | None = None
    reference_pubkey: str | None = None


@dataclass(slots=True)
class InvoiceStatusDTO:
    provider_invoice_id: str
    status: str  # created|pending|confirming|paid|underpaid|overpaid|expired|failed
    paid_amount_usd: Decimal | None = None


@dataclass(slots=True)
class PaymentEventDTO:
    provider_invoice_id: str
    status: str
    provider_event_id: str | None = None
    paid_amount_usd: Decimal | None = None


class PaymentProvider(Protocol):
    name: str

    async def create_invoice(
        self,
        *,
        order_public_id: str,
        amount_usd: Decimal,
        ttl_minutes: int,
        asset: str | None = None,
        network: str | None = None,
    ) -> InvoiceDTO: ...

    async def fetch_invoice(self, provider_invoice_id: str) -> InvoiceStatusDTO: ...

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool: ...

    def parse_event(self, raw_body: bytes) -> PaymentEventDTO: ...
