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
from dataclasses import dataclass, field, replace
from decimal import Decimal
from functools import lru_cache

from app.services.payments.onchain.assets import AssetSpec, find_spec

# Confirmations required before a deposit is treated as final, per chain.
DEFAULT_CONFIRMATIONS: dict[str, int] = {
    "tron": 19,
    "ethereum": 12,
    "bsc": 15,
    "solana": 0,      # Solana uses the "finalized" commitment instead of a count
    "bitcoin": 6,     # ~1h; 2 was cheap-double-spend range for irreversible delivery
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
class PayoutSource:
    """A wallet WE send referral payouts from — watched to auto-confirm those payouts.

    Public address only: the watcher never holds a key, it just recognises our own
    outgoing transfer on-chain and attaches the real txid to the payout record.
    """

    network: str   # trc20 | erc20 | bep20
    chain: str     # tron | ethereum | bsc
    address: str
    asset: str = "USDT"
    # Testnet override, same idea as the per-rail override in ONCHAIN_METHODS: the USDT
    # contract differs per network, and the payout scan filters by it.
    token_contract: str | None = None
    decimals: int | None = None


@dataclass(frozen=True, slots=True)
class OnchainConfig:
    methods: dict[tuple[str, str], MethodConfig]
    rpc: RpcConfig
    network: str = "mainnet"  # "mainnet" | "testnet" — selects default RPC endpoints
    payout_sources: tuple[PayoutSource, ...] = ()

    def payout_sources_for_chain(self, chain: str) -> list[PayoutSource]:
        return [s for s in self.payout_sources if s.chain == chain]

    def payout_spec(self, source: PayoutSource) -> AssetSpec | None:
        """Resolve the token spec the payout scan must filter by.

        Overrides win in the order most-specific-first: the payout source's own
        ``token_contract``, then the same rail's override in ``ONCHAIN_METHODS`` (so a
        testnet contract only has to be written once when we both accept and pay out on
        that rail), then the mainnet default. Without this the payout watcher scans for
        the mainnet USDT contract on a test chain and silently confirms nothing.
        """
        spec = find_spec(source.asset, source.network)
        if spec is None:  # pragma: no cover - _parse_payout_sources rejects these
            return None
        method = self.method(source.asset, source.network)
        if method is not None:
            spec = method.spec
        overrides: dict[str, object] = {}
        if source.token_contract:
            overrides["token_contract"] = source.token_contract
        if source.decimals is not None:
            overrides["decimals"] = source.decimals
        return replace(spec, **overrides) if overrides else spec  # type: ignore[arg-type]

    def payout_chains(self) -> set[str]:
        return {s.chain for s in self.payout_sources}

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
        # Pinned to zero, not read from the rail. There is no such thing here as an
        # amount smaller than the one we quoted counting as paid — client decision,
        # 2026-08-12. A short payment lands in the ledger as `underpaid` for a person to
        # decide on, which is the only place that decision belongs. Every rail already
        # had this unset, so nothing changes in behaviour; what changes is that it can no
        # longer be set by accident. Overpayment is unaffected — the matcher accepts it
        # up to its own cap regardless.
        tolerance_pct = Decimal(0)
        min_amount_usd = Decimal(str(entry.get("min_amount_usd", "0")))
        # per-rail overrides — needed on testnet, where the token contract/mint (and
        # sometimes decimals) differ from the mainnet defaults pinned in assets.py.
        overrides: dict[str, object] = {}
        if entry.get("token_contract"):
            overrides["token_contract"] = str(entry["token_contract"])
        if entry.get("token_mint"):
            overrides["token_mint"] = str(entry["token_mint"])
        if entry.get("decimals") is not None:
            overrides["decimals"] = int(entry["decimals"])
        if overrides:
            spec = replace(spec, **overrides)  # type: ignore[arg-type]
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


def _parse_payout_sources(sources_json: str | None) -> tuple[PayoutSource, ...]:
    """``ONCHAIN_PAYOUT_SOURCES`` — the wallets we send referral payouts from::

        [{"network": "trc20", "address": "T..."}, {"network": "erc20", "address": "0x..."}]
    """
    if not sources_json or not sources_json.strip():
        return ()
    try:
        raw = json.loads(sources_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise OnchainConfigError(f"ONCHAIN_PAYOUT_SOURCES is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise OnchainConfigError("ONCHAIN_PAYOUT_SOURCES must be a JSON array")

    from app.services.payouts import PAYOUT_RAILS, normalize_network

    out: list[PayoutSource] = []
    for entry in raw:
        network = normalize_network(str(entry.get("network", "")))
        rail = PAYOUT_RAILS.get(network)
        if rail is None:
            raise OnchainConfigError(
                f"unsupported payout network in ONCHAIN_PAYOUT_SOURCES: {network!r}"
            )
        address = str(entry.get("address", "")).strip()
        if not address:
            raise OnchainConfigError(f"payout source {network} is missing an address")
        decimals = entry.get("decimals")
        out.append(
            PayoutSource(
                network=rail.network,
                chain=rail.chain,
                address=address,
                token_contract=(
                    str(entry["token_contract"]) if entry.get("token_contract") else None
                ),
                decimals=int(decimals) if decimals is not None else None,
            )
        )
    return tuple(out)


def _reject_mainnet_contracts_on_testnet(
    methods: dict[tuple[str, str], MethodConfig],
) -> None:
    """Fail loudly when a token rail runs on testnet with its mainnet contract.

    Token contracts differ per network: the mainnet USDT contract simply does not exist
    on Nile/Sepolia/BSC-testnet. Left unnoticed, the watcher scans happily and finds
    nothing forever — a silent zero-deposit failure that looks identical to "nobody has
    paid yet". A rail must therefore carry an explicit ``token_contract`` / ``token_mint``
    override on testnet. Native coins (BTC/ETH/SOL/TRX/LTC) need none.
    """
    for (asset, network), method in methods.items():
        spec = method.spec
        if spec.is_native:
            continue
        mainnet = find_spec(asset, network)
        if mainnet is None:  # pragma: no cover - _parse_methods already rejected these
            continue
        field_name = "token_mint" if spec.token_mint else "token_contract"
        configured = spec.token_mint or spec.token_contract
        if configured != (mainnet.token_mint or mainnet.token_contract):
            continue  # overridden — trust the operator's testnet address
        raise OnchainConfigError(
            f"rail {asset}/{network} uses the MAINNET {field_name} {configured} but "
            f"ONCHAIN_NETWORK=testnet — that contract does not exist on the test chain, "
            f"so the watcher would silently never see a payment. Set '{field_name}' "
            f"on this rail in ONCHAIN_METHODS to its testnet address."
        )


def _reject_testnet_addresses_on_mainnet(
    methods: dict[tuple[str, str], MethodConfig],
) -> None:
    """Fail loudly when a rail still points at a testnet address after the switch.

    Flipping ONCHAIN_NETWORK is one variable; replacing nine addresses is nine edits, and
    the switch is exactly when one gets missed. A missed one is not a broken deploy, it is
    a checkout that hands a customer an address on the wrong chain — so this refuses to
    start rather than quote it.

    ⚠️ It can only catch the chains whose addresses carry a network in them: Bitcoin
    (`tb1…`/`m…`/`n…`/`2…`) and Litecoin (`tltc1…`/`Q…`). **Tron, Ethereum, BSC and Solana
    use the identical address format on both networks** — the same key controls the same
    address on testnet and mainnet — so nothing here or anywhere else can tell you that
    the EVM address in the config is still the throwaway wallet from testing. Those four
    have to be checked by a human against the client's wallets. That is the whole reason
    this docstring says so out loud.
    """
    testnet_prefixes = {
        "bitcoin": ("tb1", "m", "n", "2"),
        "litecoin": ("tltc1", "Q"),
    }
    for (asset, network), method in methods.items():
        prefixes = testnet_prefixes.get(method.chain)
        if not prefixes:
            continue
        if method.address.lower().startswith(tuple(p.lower() for p in prefixes)):
            raise OnchainConfigError(
                f"rail {asset}/{network} has a testnet address ({method.address}) but "
                f"ONCHAIN_NETWORK=mainnet. A customer sent here cannot pay it. Replace it "
                f"with the mainnet {method.chain} address before switching over — and "
                f"check the Tron/EVM/Solana rails by hand while you are there, because "
                f"their addresses look identical on both networks."
            )


def _reject_weak_confirmations_on_mainnet(
    methods: dict[tuple[str, str], MethodConfig],
) -> None:
    """Fail loudly when a rail waits for fewer confirmations than the chain needs.

    The mirror image of the guard above, and it exists for the same reason: testnet
    settings get copied into the mainnet config. On testnet we deliberately drop these
    thresholds — BTC ran at 1 instead of 6 so a test payment took ten minutes rather than
    an hour — and `ONCHAIN_METHODS` is one JSON blob that will be duplicated and have its
    addresses swapped when the client's real wallets arrive. The confirmation counts are
    the part nobody looks at while doing that.

    Getting this wrong costs real money quietly: a deposit finalised at one confirmation
    can still be reorged away, and by then the proxy is issued. Raising a threshold above
    the default stays allowed — that is a deliberate, safe direction. Lowering it is a
    decision that belongs in code review, not in an environment variable.
    """
    for (asset, network), method in methods.items():
        floor = DEFAULT_CONFIRMATIONS.get(method.chain, 12)
        if method.confirmations >= floor:
            continue
        raise OnchainConfigError(
            f"rail {asset}/{network} is set to {method.confirmations} confirmation(s) but "
            f"ONCHAIN_NETWORK=mainnet requires at least {floor} on {method.chain}. This is "
            f"almost always a testnet value copied into the production config — a deposit "
            f"finalised too early can be reorged away after the access is issued. Remove "
            f"'confirmations' from this rail to take the {floor} default."
        )


def _reject_mainnet_payout_contracts_on_testnet(config: OnchainConfig) -> None:
    """Same guard for the payout side, which scans by contract too.

    The payout watcher filters our outgoing transfers by the USDT contract. Left on the
    mainnet address while running on testnet it matches nothing, so payouts sit in the
    queue forever waiting for a confirmation that can never arrive.
    """
    for source in config.payout_sources:
        spec = config.payout_spec(source)
        mainnet = find_spec(source.asset, source.network)
        if spec is None or mainnet is None:  # pragma: no cover - parser rejects these
            continue
        if spec.token_contract != mainnet.token_contract:
            continue  # overridden, directly or via the matching ONCHAIN_METHODS rail
        raise OnchainConfigError(
            f"payout source {source.asset}/{source.network} uses the MAINNET "
            f"token_contract {spec.token_contract} but ONCHAIN_NETWORK=testnet — payouts "
            f"would never auto-confirm. Add 'token_contract' to this entry in "
            f"ONCHAIN_PAYOUT_SOURCES (or to the same rail in ONCHAIN_METHODS)."
        )


def load_config(
    methods_json: str | None,
    rpc_json: str | None,
    network: str = "mainnet",
    payout_sources_json: str | None = None,
    *,
    strict: bool = False,
) -> OnchainConfig:
    """Build an :class:`OnchainConfig` from the raw JSON strings (pure, testable).

    ``strict`` turns on the checks that only make sense for a configuration someone
    deployed, as opposed to one a test assembled. Right now that is the mainnet
    confirmation floor: unit tests deliberately drive rails at two or three confirmations
    to exercise the confirming→paid transition without inventing long fake chains, and
    holding them to a production threshold would test a different thing than they mean to.
    ``get_onchain_config`` — the only path the running application takes — sets it.
    """
    methods = _parse_methods(methods_json)
    resolved_network = "testnet" if str(network).lower() == "testnet" else "mainnet"
    if resolved_network == "testnet":
        _reject_mainnet_contracts_on_testnet(methods)
    elif strict:
        _reject_weak_confirmations_on_mainnet(methods)
        _reject_testnet_addresses_on_mainnet(methods)
    config = OnchainConfig(
        methods=methods,
        rpc=_parse_rpc(rpc_json),
        network=resolved_network,
        payout_sources=_parse_payout_sources(payout_sources_json),
    )
    if resolved_network == "testnet":
        _reject_mainnet_payout_contracts_on_testnet(config)
    return config


# The rail list the console has saved, as the same JSON string ``load_config`` parses.
# ``None`` means nobody has saved one and ONCHAIN_METHODS is still in charge — which is
# how every existing deploy keeps working until an operator presses Save for the first
# time. Installed by ``rails.refresh_rails``; see that module for why it is a module
# global rather than a lookup inside the parser.
_rails_override: str | None = None


def set_rails_override(methods_json: str | None) -> None:
    """Install (or clear) the console-managed rail list for this process."""
    global _rails_override
    if methods_json != _rails_override:
        _rails_override = methods_json
        get_onchain_config.cache_clear()


@lru_cache(maxsize=1)
def get_onchain_config() -> OnchainConfig:
    """Cached config built from application settings."""
    from app.core.config import settings

    return load_config(
        settings.onchain_methods if _rails_override is None else _rails_override,
        settings.onchain_rpc,
        settings.onchain_network,
        settings.onchain_payout_sources,
        strict=True,
    )


def rails_are_console_managed() -> bool:
    """True once a rail list has been saved from the console."""
    return _rails_override is not None


def reset_config_cache() -> None:
    """Drop the cached config (tests / settings reload)."""
    global _rails_override
    _rails_override = None
    get_onchain_config.cache_clear()
