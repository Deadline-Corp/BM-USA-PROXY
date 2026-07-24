"""Canonical registry of supported (asset, network) payment methods.

One ``AssetSpec`` per accepted crypto rail. This is the single source of truth for
which chain a rail lives on, how many on-chain decimals its base unit uses, the token
contract / SPL mint to watch, and the precision we quote payment amounts at.

Token contracts are mainnet addresses — VERIFY against a block explorer before enabling
a rail in production (a wrong contract = watching the wrong token).
"""

from __future__ import annotations

from dataclasses import dataclass

# Chains we run a watcher engine for.
TRON = "tron"
ETHEREUM = "ethereum"
BSC = "bsc"
SOLANA = "solana"
BITCOIN = "bitcoin"
LITECOIN = "litecoin"

CHAINS: frozenset[str] = frozenset({TRON, ETHEREUM, BSC, SOLANA, BITCOIN, LITECOIN})


@dataclass(frozen=True, slots=True)
class AssetSpec:
    """Immutable description of one accepted (asset, network) rail."""

    asset: str            # ticker shown to the buyer: USDT, USDC, BTC, ETH, SOL, TRX, LTC
    network: str          # rail: trc20, erc20, bep20, spl, native
    chain: str            # engine that watches it
    decimals: int         # on-chain base-unit decimals (for base-unit ↔ human conversion)
    is_stable: bool       # True → oracle rate is pinned to 1.0 USD
    quote_decimals: int   # decimals we round the quoted payment amount to
    token_contract: str | None = None  # EVM/Tron token contract (None = native coin)
    token_mint: str | None = None      # Solana SPL mint (None = native SOL)

    @property
    def key(self) -> tuple[str, str]:
        return (self.asset, self.network)

    @property
    def is_native(self) -> bool:
        return self.token_contract is None and self.token_mint is None


# Mainnet token contracts / SPL mints — PUBLIC on-chain addresses (not secrets).
# VERIFY each against a block explorer before enabling its rail in production.
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
USDT_SPL = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDC_ERC20 = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
USDC_BEP20 = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
USDC_SPL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# NOTE: BEP-20 USDT/USDC use 18 decimals (unlike their 6-decimal ERC-20 / TRC-20 forms).
_SPECS: tuple[AssetSpec, ...] = (
    # ── stablecoins ────────────────────────────────────────────────────────
    AssetSpec("USDT", "trc20", TRON, 6, True, 6, token_contract=USDT_TRC20),
    AssetSpec("USDT", "erc20", ETHEREUM, 6, True, 6, token_contract=USDT_ERC20),
    AssetSpec("USDT", "bep20", BSC, 18, True, 6, token_contract=USDT_BEP20),
    AssetSpec("USDT", "spl", SOLANA, 6, True, 6, token_mint=USDT_SPL),
    AssetSpec("USDC", "erc20", ETHEREUM, 6, True, 6, token_contract=USDC_ERC20),
    AssetSpec("USDC", "bep20", BSC, 18, True, 6, token_contract=USDC_BEP20),
    AssetSpec("USDC", "spl", SOLANA, 6, True, 6, token_mint=USDC_SPL),
    # ── native coins (volatile) ────────────────────────────────────────────
    AssetSpec("SOL", "native", SOLANA, 9, False, 6),
    AssetSpec("BTC", "native", BITCOIN, 8, False, 8),
    AssetSpec("ETH", "native", ETHEREUM, 18, False, 8),
    AssetSpec("TRX", "native", TRON, 6, False, 6),
    AssetSpec("LTC", "native", LITECOIN, 8, False, 8),
)

SPECS: dict[tuple[str, str], AssetSpec] = {s.key: s for s in _SPECS}

# The coingecko id used to price each volatile asset (stablecoins are pinned to 1.0).
COINGECKO_IDS: dict[str, str] = {
    "SOL": "solana",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "TRX": "tron",
    "LTC": "litecoin",
}


def get_spec(asset: str, network: str) -> AssetSpec:
    """Return the spec for a rail, raising ``KeyError`` if it is not supported."""
    return SPECS[(asset.upper(), network.lower())]


def find_spec(asset: str, network: str) -> AssetSpec | None:
    return SPECS.get((asset.upper(), network.lower()))
