"""Build the right ``ChainClient`` for a chain from the on-chain RPC config.

Chains without an engine yet (EVM/UTXO/Solana — later phases) return ``None`` so the
watcher cron simply skips them until their phase lands.
"""

from __future__ import annotations

from app.services.payments.onchain.chain_client import ChainClient
from app.services.payments.onchain.config import OnchainConfig

# Keyless fallbacks so a rail is never silently skipped. PRODUCTION SHOULD SET ONCHAIN_RPC
# to a keyed provider — these public endpoints have no SLA and rate-limit under load; they
# exist so a missing config degrades to "slower" instead of "this chain is not watched".
# Verified 2026-07-31: address-filtered eth_getLogs returns real USDT transfers on both EVM
# endpoints (wider ranges are handled by the splitting in EvmClient._get_logs).
_DEFAULT_ENDPOINTS: dict[str, str] = {
    "tron": "https://api.trongrid.io",
    "ethereum": "https://ethereum-rpc.publicnode.com",
    "bsc": "https://bsc-rpc.publicnode.com",
    "bitcoin": "https://mempool.space/api",
    "litecoin": "https://litecoinspace.org/api",
    "solana": "https://api.mainnet-beta.solana.com",
}

# Public testnet defaults (override any via ONCHAIN_RPC). Tron=Nile, EVM=Sepolia/BSC-testnet,
# Solana=devnet, Bitcoin=testnet4, Litecoin=testnet.
_TESTNET_ENDPOINTS: dict[str, str] = {
    "tron": "https://nile.trongrid.io",
    "ethereum": "https://ethereum-sepolia-rpc.publicnode.com",
    # NOT data-seed-prebsc: measured 2026-07-31, it refuses eth_getLogs outright
    # ("limit exceeded") even for a 5-block span, so the watcher could never scan.
    # publicnode accepts our address-filtered queries (~50 blocks; wider ranges are handled
    # by the range splitting in EvmClient._get_logs).
    "bsc": "https://bsc-testnet-rpc.publicnode.com",
    "solana": "https://api.devnet.solana.com",
    "bitcoin": "https://mempool.space/testnet4/api",
    "litecoin": "https://litecoinspace.org/testnet/api",
}

_EVM_CHAINS = frozenset({"ethereum", "bsc"})
_UTXO_CHAINS = frozenset({"bitcoin", "litecoin"})


def _default_endpoint(chain: str, network: str) -> str | None:
    if network == "testnet":
        return _TESTNET_ENDPOINTS.get(chain)
    return _DEFAULT_ENDPOINTS.get(chain)

# Max scan window per tick, in the chain's cursor units.
# Tron cursor = milliseconds; EVM/UTXO cursor = block numbers; Solana cursor = slots.
_MAX_SCAN: dict[str, int] = {
    "tron": 15 * 60 * 1000,  # 15 minutes of transfers
    "ethereum": 100,         # ~20 min of blocks; native scan iterates each block
    # 1000, and the number has to be re-derived when a chain changes its block time, not
    # copied forward. This said 200 with the note "~10 min of 3s blocks", which was true of
    # BSC once. Measured from our own ledger on 2026-09-04 — 705 confirmations in 315
    # seconds — it now makes 2.24 blocks a second, so 200 blocks is 90 seconds, not ten
    # minutes. Against a 300-second quiet window that is a 470-block deficit per window,
    # and the deposit cursor had drifted 9,796 blocks behind the head before anyone noticed.
    # A scan must cover more chain than the longest gap between two scans.
    "bsc": 1000,
    # UTXO/Solana walk the address/signature API (not per-block): cursor jumps to tip
    "bitcoin": 10_000,
    "litecoin": 10_000,
    "solana": 10_000,
}


def build_client(chain: str, config: OnchainConfig) -> ChainClient | None:
    """Construct the engine for ``chain``, or ``None`` if unimplemented / unconfigured."""
    endpoint = config.rpc.endpoint(chain) or _default_endpoint(chain, config.network)
    if chain == "tron":
        from app.services.payments.onchain.clients.tron import TronClient

        return TronClient(endpoint=endpoint or "", api_key=config.rpc.api_key("tron"))
    if chain in _EVM_CHAINS:
        from app.services.payments.onchain.clients.evm import EvmClient

        if not endpoint:  # EVM mainnet needs a provider URL (Infura/Alchemy/public node)
            return None
        return EvmClient(chain=chain, endpoint=endpoint)
    if chain in _UTXO_CHAINS:
        from app.services.payments.onchain.clients.utxo import UtxoClient

        return UtxoClient(chain=chain, endpoint=endpoint or "")
    if chain == "solana":
        from app.services.payments.onchain.clients.solana import SolanaClient

        return SolanaClient(endpoint=endpoint or "")
    return None


def chain_max_scan(chain: str) -> int:
    """Per-tick scan-window cap for a chain (cursor units)."""
    return _MAX_SCAN.get(chain, 500)


# How far back each tick re-scans behind the cursor, in the chain's cursor units.
#
# A cursor that only ever moves forward assumes the API had already indexed a transfer by
# the time its window was scanned. When that assumption breaks — indexer lag, a node a
# second behind, a provider that briefly 500s — the transfer falls in a span that is never
# looked at again and the payment is lost silently. Re-scanning a trailing window costs a
# little duplicate work and is safe: process_transfer short-circuits on deposits that
# already reached a terminal ledger status.
_RESCAN_OVERLAP: dict[str, int] = {
    "tron": 5 * 60 * 1000,  # 5 min of ms-cursor — well past Tron's ~57s solidity lag
    "ethereum": 10,         # blocks
    "bsc": 20,
    "bitcoin": 3,
    "litecoin": 3,
    "solana": 150,          # slots (~1 min)
}


def chain_rescan_overlap(chain: str) -> int:
    """How far behind the cursor to start each scan (cursor units)."""
    return _RESCAN_OVERLAP.get(chain, 0)
