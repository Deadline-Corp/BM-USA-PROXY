"""Central configuration. Every environment variable is declared here exactly once."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["local", "staging", "prod"]


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
    bot_webhook_secret: str = "change-me"  # noqa: S105  dev default, overridden by env
    ops_alert_chat_id: str | None = None

    # Admin auth
    admin_jwt_secret: str = "change-me-in-prod-please-32bytes-min"  # noqa: S105  dev default
    admin_jwt_ttl_min: int = 30
    admin_refresh_ttl_days: int = 14
    seed_admin_email: str = "admin@bmusproxy.local"
    seed_admin_password: str | None = None

    # Encryption
    credentials_key: str | None = None

    # iproxy
    iproxy_api_key: str | None = None
    iproxy_base_url: str = "https://api.iproxy.online"

    # Payments
    payment_provider: str = "mock"
    payment_api_key: str | None = None
    payment_webhook_secret: str | None = None

    # Feature flags
    feature_real_payments: bool = False
    seed_dev_fixtures: bool = True

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def sync_database_url(self) -> str:
        """Alembic uses a sync driver; swap asyncpg → psycopg where needed."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
