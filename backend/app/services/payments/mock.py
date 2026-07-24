"""MockPaymentProvider — drives the checkout flow on staging without a real processor.

Invoices start 'pending'; a dev-only endpoint (POST /api/twa/orders/{id}/_mock_pay)
marks them paid. Swapped for a real adapter in Stage 3 (DG-1) with zero call-site changes.
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.services.payments.base import (
    InvoiceDTO,
    InvoiceStatusDTO,
    PaymentEventDTO,
)


class MockPaymentProvider:
    name = "mock"

    async def create_invoice(
        self,
        *,
        order_public_id: str,
        amount_usd: Decimal,
        ttl_minutes: int,
        asset: str | None = None,
        network: str | None = None,
    ) -> InvoiceDTO:
        return InvoiceDTO(
            provider_invoice_id=f"mock-{order_public_id}",
            payment_url=f"/api/twa/orders/{order_public_id}/_mock_pay",
            pay_address="TMockAddr000000000000000000000000000",
            crypto_currency="USDT",
            crypto_network="TRC20",
            crypto_amount=amount_usd,  # 1:1 in mock
            expires_at_epoch=0,  # filled by caller from ttl
        )

    async def fetch_invoice(self, provider_invoice_id: str) -> InvoiceStatusDTO:
        return InvoiceStatusDTO(provider_invoice_id=provider_invoice_id, status="pending")

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        return True

    def parse_event(self, raw_body: bytes) -> PaymentEventDTO:
        data = json.loads(raw_body or b"{}")
        return PaymentEventDTO(
            provider_invoice_id=data.get("provider_invoice_id", ""),
            status=data.get("status", "paid"),
            provider_event_id=data.get("event_id"),
        )
