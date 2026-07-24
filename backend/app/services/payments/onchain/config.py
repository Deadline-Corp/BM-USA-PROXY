"""Runtime configuration for the on-chain watcher.

Two JSON env vars drive everything (see ``app.core.config.Settings``):

* ``ONCHAIN_METHODS`` — array of enabled rails + their **receiving addresses**::

      [
        {"asset": "USDT", "network": "trc20", "address": "T...",
         "confirmations": 19, "tolerance_pct": "0", "min_amount_usd": "1"},
        {"asset": "TRX",  "network": "native", "address": "T..."}
      ]

* ``ONCHAIN_RPC`` — per-chain endpoint + optional api key::

      {"tron": {"url": "https://api.trongrid.io", "api_key": "..."},
       "ethereum": {"url": "https://..."}, "solana": {"url": "https://..."}}

The backend is **watch-only**: it stores public receiving addresses only, never a seed
or xpub. Sweeping is out of scope by design (single shared address per rail).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache

from app.services.payments.onchain.assets import AssetSpec, find_spec

# Confirmations required before a deposit is treated as final, per chain.
DEFAULT_CONFIRMATIONS: dict[str, int] = {
    "tron": 19,
    "ethereum": 12,
    "bsc": 15,
    "solana": 0,      # Solana uses the "finalized" commitment instead of a count
    "bitcoin": 2,
    "litecoin": 6,
}


class OnchainConfigError(RuntimeError):
    """Raised when the on-chain configuration is missing or malformed."""


@dataclass(frozen=True, slots=True)
class MethodConfig:
    """One enabled rail plus its operational parameters."""

    spec: AssetSpec
    address: str
    confirmations: int
    tolerance_pct: Decimal
    min_amount_usd: Decimal

    @property
    def asset(self) -> str:
        return self.spec.asset

    @property
    def network(self) -> str:
        return self.spec.network

    @property
    def chain(self) -> str:
        return self.spec.chain


@dataclass(frozen=True, slots=True)
class RpcConfig:
    endpoints: dict[str, str] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)

    def endpoint(self, chain: str) -> str | None:
        return self.endpoints.get(chain)

    def api_key(self, chain: str) -> str | None:
        return self.api_keys.get(chain)

    def require_endpoint(self, chain: str) -> str:
        url = self.endpoints.get(chain)
        if not url:
            raise OnchainConfigError(f"no RPC endpoint configured for chain '{chain}'")
        return url


@dataclass(frozen=True, slots=True)
class OnchainConfig:
    methods: dict[tuple[str, str], MethodConfig]
    rpc: RpcConfig

    def method(self, asset: str, network: str) -> MethodConfig | None:
        return self.methods.get((asset.upper(), network.lower()))

    def require_method(self, asset: str, network: str) -> MethodConfig:
        m = self.method(asset, network)
        if m is None:
            raise OnchainConfigError(f"rail '{asset}/{network}' is not enabled")
        return m

    def enabled_methods(self) -> list[MethodConfig]:
        return list(self.methods.values())

    def chains_in_use(self) -> set[str]:
        return {m.chain for m in self.methods.values()}

    def methods_for_chain(self, chain: str) -> list[MethodConfig]:
        return [m for m in self.methods.values() if m.chain == chain]

    def default_method(self) -> MethodConfig | None:
        """First configured rail — used when a caller does not specify asset/network."""
        return next(iter(self.methods.values()), None)


def _parse_methods(methods_json: str | None) -> dict[tuple[str, str], MethodConfig]:
    if not methods_json or not methods_json.strip():
        return {}
    try:
        raw = json.loads(methods_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise OnchainConfigError(f"ONCHAIN_METHODS is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise OnchainConfigError("ONCHAIN_METHODS must be a JSON array")

    out: dict[tuple[str, str], MethodConfig] = {}
    for entry in raw:
        asset = str(entry.get("asset", "")).upper()
        network = str(entry.get("network", "")).lower()
        spec = find_spec(asset, network)
        if spec is None:
            raise OnchainConfigError(f"unsupported rail in ONCHAIN_METHODS: {asset}/{network}")
        address = str(entry.get("address", "")).strip()
        if not address:
            raise OnchainConfigError(f"rail {asset}/{network} is missing a receiving address")
        confirmations = int(
            entry.get("confirmations", DEFAULT_CONFIRMATIONS.get(spec.chain, 12))
        )
        tolerance_pct = Decimal(str(entry.get("tolerance_pct", "0")))
        min_amount_usd = Decimal(str(entry.get("min_amount_usd", "0")))
        out[spec.key] = MethodConfig(
            spec=spec,
            address=address,
            confirmations=confirmations,
            tolerance_pct=tolerance_pct,
            min_amount_usd=min_amount_usd,
        )
    return out


def _parse_rpc(rpc_json: str | None) -> RpcConfig:
    if not rpc_json or not rpc_json.strip():
        return RpcConfig()
    try:
        raw = json.loads(rpc_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise OnchainConfigError(f"ONCHAIN_RPC is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise OnchainConfigError("ONCHAIN_RPC must be a JSON object")

    endpoints: dict[str, str] = {}
    api_keys: dict[str, str] = {}
    for chain, cfg in raw.items():
        if isinstance(cfg, str):
            endpoints[chain] = cfg
        elif isinstance(cfg, dict):
            if cfg.get("url"):
                endpoints[chain] = str(cfg["url"])
            if cfg.get("api_key"):
                api_keys[chain] = str(cfg["api_key"])
        else:  # pragma: no cover - defensive
            raise OnchainConfigError(f"ONCHAIN_RPC['{chain}'] must be a string or object")
    return RpcConfig(endpoints=endpoints, api_keys=api_keys)


def load_config(methods_json: str | None, rpc_json: str | None) -> OnchainConfig:
    """Build an :class:`OnchainConfig` from the two raw JSON strings (pure, testable)."""
    return OnchainConfig(methods=_parse_methods(methods_json), rpc=_parse_rpc(rpc_json))


@lru_cache(maxsize=1)
def get_onchain_config() -> OnchainConfig:
    """Cached config built from application settings."""
    from app.core.config import settings

    return load_config(settings.onchain_methods, settings.onchain_rpc)


def reset_config_cache() -> None:
    """Drop the cached config (tests / settings reload)."""
    get_onchain_config.cache_clear()
