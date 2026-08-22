"""Central configuration. Every environment variable is declared here exactly once."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["local", "staging", "prod"]

# Insecure dev defaults — MUST be overridden in prod (enforced by the validator below).
_DEFAULT_WEBHOOK_SECRET = "change-me"  # noqa: S105
_DEFAULT_JWT_SECRET = "change-me-in-prod-please-32bytes-min"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core
    env: Env = "local"
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    sentry_dsn: str | None = None

    # Database / Redis
    database_url: str = "postgresql+asyncpg://bm:bm@localhost:5432/bm_usa_proxy"
    redis_url: str = "redis://localhost:6379/0"

    # Telegram bot
    bot_token: str | None = None
    bot_webhook_secret: str = _DEFAULT_WEBHOOK_SECRET
    ops_alert_chat_id: str | None = None

    # Admin auth
    admin_jwt_secret: str = _DEFAULT_JWT_SECRET
    admin_jwt_ttl_min: int = 30
    admin_refresh_ttl_days: int = 14
    seed_admin_email: str = "admin@bmusproxy.local"
    seed_admin_password: SecretStr | None = None

    # Encryption
    credentials_key: str | None = None

    # iproxy
    iproxy_api_key: str | None = None
    iproxy_base_url: str = "https://iproxy.online"

    # Payments
    payment_provider: str = "mock"
    payment_api_key: str | None = None
    payment_webhook_secret: str | None = None

    # On-chain watcher (provider='onchain'; see doc 15). Both are raw JSON strings.
    onchain_methods: str | None = None  # array of enabled rails + receiving addresses
    onchain_rpc: str | None = None      # object of per-chain RPC endpoints + api keys
    onchain_network: Literal["mainnet", "testnet"] = "mainnet"  # selects default RPC endpoints
    # wallets we SEND referral payouts from — watched to auto-confirm those payouts
    # (public addresses only): [{"network":"trc20","address":"T..."}]
    onchain_payout_sources: str | None = None

    # AI support assistant (bot answers simple product questions; see services/ai_support.py).
    # Absent key = the whole layer stays asleep and every message goes to an operator, which
    # is also the behaviour the two admin toggles fall back to.
    # Deliberately NOT named ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL: those are the SDK's
    # own conventional names, they are already set globally on machines with Anthropic
    # tooling installed, and a real environment variable outranks the .env file. Measured
    # here — a stray ANTHROPIC_BASE_URL silently sent every request to the wrong host.
    # Signing keys for Alchemy address-activity webhooks, as {"ETH_MAINNET": "whsec_..."}.
    # A delivery is a doorbell, never a receipt — see services.payments.onchain.webhooks.
    alchemy_webhook_keys: str | None = None

    ai_support_api_key: str | None = None
    ai_support_base_url: str | None = None
    ai_support_model: str = "claude-haiku-4-5"

    # Feature flags
    feature_real_payments: bool = False
    feature_real_provisioning: bool = False  # real iproxy issuance (decoupled from payments)
    seed_dev_fixtures: bool = True

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @model_validator(mode="after")
    def _require_prod_secrets(self) -> Settings:
        """Fail closed: any non-local env must not boot on default/missing/weak secrets.

        Only an explicit ``ENV=local`` is exempt (CWE-798 / CWE-1188). A public staging
        tier registers a Telegram webhook and is internet-reachable, so it must be held
        to the same bar as prod — a default ``BOT_WEBHOOK_SECRET`` there is forgeable.

        Provider-specific validation is also applied: when ``payment_provider=onchain``,
        ``ONCHAIN_METHODS`` and ``ONCHAIN_RPC`` must be set; the mock provider is
        left alone — it is refused entirely by the provider registry wherever it matters.
        """
        if self.env == "local":
            return self
        missing: list[str] = []
        if self.admin_jwt_secret == _DEFAULT_JWT_SECRET or len(self.admin_jwt_secret) < 32:
            missing.append("ADMIN_JWT_SECRET (default or shorter than 32 chars)")
        if self.bot_webhook_secret == _DEFAULT_WEBHOOK_SECRET:
            missing.append("BOT_WEBHOOK_SECRET")
        if not self.credentials_key:
            missing.append("CREDENTIALS_KEY")
        # Core infra: a non-local deployment cannot run without these.
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.database_url or "postgresql+asyncpg://" not in self.database_url:
            missing.append("DATABASE_URL")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if self.feature_real_payments:
            if self.payment_provider == "mock":
                missing.append("PAYMENT_PROVIDER (still 'mock')")
            if not self.payment_webhook_secret:
                missing.append("PAYMENT_WEBHOOK_SECRET")
        # Provider-specific startup validation — the config that each provider needs to
        # actually work, checked once at boot rather than failing on the first request.
        if self.payment_provider == "onchain":
            if not self.onchain_methods:
                missing.append("ONCHAIN_METHODS (required when PAYMENT_PROVIDER=onchain)")
            if not self.onchain_rpc:
                missing.append("ONCHAIN_RPC (required when PAYMENT_PROVIDER=onchain)")
        # No rule for the mock provider here. It reads as a missing gate, but the secret
        # is not one: MockPaymentProvider.verify_webhook returns True unconditionally and
        # never looks at it, so demanding it would buy nothing and refuse to boot a staging
        # tier that is legitimately running the mock with no money in play. What actually
        # protects that is payments/registry.get_payment_provider, which refuses the mock
        # outright once is_prod or feature_real_payments is set — the guard is in the place
        # that can enforce it.
        if missing:
            raise ValueError(
                f"{self.env} refuses to start with default/missing/weak secrets: "
                + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
