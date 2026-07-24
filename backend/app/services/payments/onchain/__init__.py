"""Self-hosted multi-chain on-chain payment watcher (doc 15).

Public surface:
* :class:`OnchainProvider` — the ``PaymentProvider`` adapter (invoice creation, stateless).
* :func:`run_chain_tick` — one watcher pass for a single chain (worker side).
* :class:`ChainClient` / :class:`IncomingTransfer` — the per-chain engine interface.
"""

from __future__ import annotations

from app.services.payments.onchain.chain_client import ChainClient, IncomingTransfer
from app.services.payments.onchain.config import (
    MethodConfig,
    OnchainConfig,
    OnchainConfigError,
    get_onchain_config,
    load_config,
    reset_config_cache,
)
from app.services.payments.onchain.provider import OnchainProvider
from app.services.payments.onchain.watcher import TickReport, run_chain_tick

__all__ = [
    "ChainClient",
    "IncomingTransfer",
    "MethodConfig",
    "OnchainConfig",
    "OnchainConfigError",
    "OnchainProvider",
    "TickReport",
    "get_onchain_config",
    "load_config",
    "reset_config_cache",
    "run_chain_tick",
]
