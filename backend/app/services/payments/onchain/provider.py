"""``PaymentProvider`` adapter for the self-hosted on-chain watcher.

Invoice creation is stateless: pick the rail, lock the USD→crypto rate, compute a unique
expected amount, and hand back the shared receiving address. The watcher (worker side)
then detects the matching deposit and drives activation through the same idempotent
``processing`` path every provider uses — this adapter never mutates the DB.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.errors import PaymentsUnconfigured
from app.services.payments.base import (
    InvoiceDTO,
    InvoiceStatusDTO,
    PaymentEventDTO,
)
from app.services.payments.onchain.amounts import absolute_tolerance, expected_amount
from app.services.payments.onchain.config import (
    MethodConfig,
    OnchainConfig,
    OnchainConfigError,
    get_onchain_config,
)
from app.services.payments.onchain.oracle import PriceOracle, get_oracle
from app.services.payments.onchain.reference_allocator import derive_reference


class OnchainProvider:
    """Implements the ``PaymentProvider`` protocol for on-chain crypto rails."""

    name = "onchain"

    def __init__(
        self,
        config: OnchainConfig | None = None,
        oracle: PriceOracle | None = None,
    ) -> None:
        # Held only when a caller passes one in (tests do). Left as None, the config is
        # read at the moment it is used — see `_cfg`.
        self._pinned_config = config
        self._oracle = oracle or get_oracle()

    @property
    def _config(self) -> OnchainConfig:
        """The rails as they are right now, not as they were when this object was built.

        get_payment_provider() is lru_cached, so this provider is constructed once per
        process — and in guard_order_attempt it is constructed one line *before* the rails
        are loaded from the database. Snapshotting in __init__ therefore froze an empty
        rail list for the life of the process: every later check passed (those read the
        live config) and then invoice creation failed with "rail 'USDT/trc20' is not
        enabled". Measured on production: the address was configured, the mini app listed
        it, and every purchase returned 500.

        Reading through means an address an operator changes in the console takes effect on
        the next invoice rather than the next deploy, which is the behaviour the Wallets
        screen already promises.
        """
        return self._pinned_config or get_onchain_config()

    def _resolve_method(self, asset: str | None, network: str | None) -> MethodConfig:
        if asset and network:
            return self._config.require_method(asset, network)
        method = self._config.default_method()
        if method is None:
            # Zero rails configured at all (vs. a specific asset/network not being one of
            # them) — the only case that means "an admin hasn't set this up yet" rather than
            # a malformed config, so it gets the buyer/business-owner-facing domain error
            # instead of the internal-only OnchainConfigError other failures below still use.
            raise PaymentsUnconfigured(
                "Payments are not set up yet: an administrator must add at least one "
                "receiving wallet address in the admin console (Wallets), after which "
                "purchases will work."
            )
        return method

    async def create_invoice(
        self,
        *,
        order_public_id: str,
        amount_usd: Decimal,
        ttl_minutes: int,
        asset: str | None = None,
        network: str | None = None,
    ) -> InvoiceDTO:
        method = self._resolve_method(asset, network)
        spec = method.spec
        # Enforce the per-rail minimum (was parsed from config but never read), so a
        # deposit can't be quoted below the amount that makes network fees worthwhile.
        if method.min_amount_usd > 0 and amount_usd < method.min_amount_usd:
            raise OnchainConfigError(
                f"amount {amount_usd} is below the {spec.asset}/{spec.network} "
                f"minimum of {method.min_amount_usd} USD"
            )

        quote = await self._oracle.quote(amount_usd, spec)
        expected = expected_amount(quote.crypto_amount, spec, order_public_id)
        tolerance = absolute_tolerance(expected, method.tolerance_pct)
        reference = derive_reference(order_public_id) if spec.chain == "solana" else None

        expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        return InvoiceDTO(
            provider_invoice_id=secrets.token_hex(16),
            payment_url=None,
            pay_address=method.address,
            crypto_currency=spec.asset,
            crypto_network=spec.network,
            crypto_amount=expected,
            expires_at_epoch=int(expires_at.timestamp()),
            chain=spec.chain,
            base_amount=quote.crypto_amount,
            amount_tolerance=tolerance,
            locked_rate=quote.rate,
            reference_pubkey=reference,
        )

    async def fetch_invoice(self, provider_invoice_id: str) -> InvoiceStatusDTO:
        # State is advanced by the watcher, not by polling; report "pending" (a no-op for
        # the forward-only state machine) so reconciliation never regresses a paid invoice.
        return InvoiceStatusDTO(provider_invoice_id=provider_invoice_id, status="pending")

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        # On-chain has no external webhook — events are emitted internally by the watcher.
        return False

    def parse_event(self, raw_body: bytes) -> PaymentEventDTO:  # pragma: no cover - never called
        raise NotImplementedError("on-chain events are emitted internally by the watcher")
