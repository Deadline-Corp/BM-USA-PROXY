"""Resolve the active PaymentProvider from settings (DG-1)."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.payments.base import PaymentProvider
from app.services.payments.mock import MockPaymentProvider


@lru_cache
def get_payment_provider() -> PaymentProvider:
    provider = settings.payment_provider.lower()
    if provider == "mock":
        # The mock accepts any webhook (verify_webhook→True); never allow it once
        # real money is on: mirror the _mock_pay / get_provisioner guard.
        if settings.is_prod or settings.feature_real_payments:
            raise RuntimeError(
                "PAYMENT_PROVIDER='mock' is forbidden when prod/real-payments are enabled"
            )
        return MockPaymentProvider()
    if provider == "onchain":
        # self-hosted multi-chain watcher (doc 15). Imported lazily so the on-chain
        # config is only parsed when this rail is actually selected.
        from app.services.payments.onchain import OnchainProvider

        return OnchainProvider()
    # Stage 3 (DG-1): bitpay | coinbase | cryptomus adapters registered here.
    raise NotImplementedError(f"payment provider '{provider}' not implemented yet")
