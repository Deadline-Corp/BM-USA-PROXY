"""Build the right ``ChainClient`` for a chain from the on-chain RPC config.

Chains without an engine yet (EVM/UTXO/Solana — later phases) return ``None`` so the
watcher cron simply skips them until their phase lands.
"""

from __future__ import annotations

from app.services.payments.onchain.chain_client import ChainClient
from app.services.payments.onchain.config import OnchainConfig

_DEFAULT_ENDPOINTS: dict[str, str] = {
    "tron": "https://api.trongrid.io",
}

_EVM_CHAINS = frozenset({"ethereum", "bsc"})

# Max scan window per tick, in the chain's cursor units.
# Tron cursor = milliseconds; EVM/UTXO cursor = block numbers.
_MAX_SCAN: dict[str, int] = {
    "tron": 15 * 60 * 1000,  # 15 minutes of transfers
    "ethereum": 100,         # ~20 min of blocks; native scan iterates each block
    "bsc": 200,              # ~10 min of 3s blocks
}


def build_client(chain: str, config: OnchainConfig) -> ChainClient | None:
    """Construct the engine for ``chain``, or ``None`` if unimplemented / unconfigured."""
    if chain == "tron":
        from app.services.payments.onchain.clients.tron import TronClient

        endpoint = config.rpc.endpoint("tron") or _DEFAULT_ENDPOINTS["tron"]
        return TronClient(endpoint=endpoint, api_key=config.rpc.api_key("tron"))
    if chain in _EVM_CHAINS:
        from app.services.payments.onchain.clients.evm import EvmClient

        evm_endpoint = config.rpc.endpoint(chain)
        if not evm_endpoint:  # EVM needs a provider URL (Infura/Alchemy/public node)
            return None
        return EvmClient(chain=chain, endpoint=evm_endpoint)
    return None


def chain_max_scan(chain: str) -> int:
    """Per-tick scan-window cap for a chain (cursor units)."""
    return _MAX_SCAN.get(chain, 500)
