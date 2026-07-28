"""Build the right ``ChainClient`` for a chain from the on-chain RPC config.

Chains without an engine yet (EVM/UTXO/Solana — later phases) return ``None`` so the
watcher cron simply skips them until their phase lands.
"""

from __future__ import annotations

from app.services.payments.onchain.chain_client import ChainClient
from app.services.payments.onchain.config import OnchainConfig

_DEFAULT_ENDPOINTS: dict[str, str] = {
    "tron": "https://api.trongrid.io",
    "bitcoin": "https://mempool.space/api",
    "litecoin": "https://litecoinspace.org/api",
    "solana": "https://api.mainnet-beta.solana.com",
    # ethereum/bsc mainnet have no reliable keyless public RPC → require ONCHAIN_RPC.
}

# Public testnet defaults (override any via ONCHAIN_RPC). Tron=Nile, EVM=Sepolia/BSC-testnet,
# Solana=devnet, Bitcoin=testnet4, Litecoin=testnet.
_TESTNET_ENDPOINTS: dict[str, str] = {
    "tron": "https://nile.trongrid.io",
    "ethereum": "https://ethereum-sepolia-rpc.publicnode.com",
    "bsc": "https://data-seed-prebsc-1-s1.binance.org:8545",
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
    "bsc": 200,              # ~10 min of 3s blocks
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
