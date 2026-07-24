"""Per-chain ``ChainClient`` engine implementations + a factory to build them.

Each client talks to one chain's RPC/indexer and is pure chain access (no DB). They are
constructed on demand by :func:`build_client` from the on-chain RPC config.
"""

from __future__ import annotations

from app.services.payments.onchain.clients.factory import build_client, chain_max_scan

__all__ = ["build_client", "chain_max_scan"]
