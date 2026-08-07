"""Build the wallet deep-link we put behind a payment QR code.

One implementation for both sides of the product: the buyer's checkout screen and the
operator's payout instruction. Each chain family has its own (or no) URI standard:

* EVM  — EIP-681. Native coin carries ``value``; a token becomes a ``/transfer`` call.
* UTXO — BIP-21 (``bitcoin:``/``litecoin:``), amount in whole coins.
* Solana— Solana Pay (``solana:``), ``spl-token`` names the mint for token payments.
* Tron  — no comparable standard is honoured by the major wallets, so we return ``None``
  and the caller falls back to a QR of the bare address.

⚠️ The EVM chain id MUST follow the configured network. Emitting mainnet ids while the
backend runs on testnet would make a scanned QR open the wallet on **mainnet**, where the
buyer has real funds — a test flow could then spend real money.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.payments.onchain.assets import AssetSpec

# chain -> (mainnet id, testnet id). Testnet ids: Sepolia, BSC Testnet.
_EVM_CHAIN_IDS: dict[str, tuple[int, int]] = {
    "ethereum": (1, 11155111),
    "bsc": (56, 97),
}


def _plain(amount: Decimal) -> str:
    """Decimal without exponent notation — wallets reject '1E-7'."""
    return format(amount.normalize(), "f")


def build_payment_uri(
    *,
    spec: AssetSpec,
    to_address: str,
    amount: Decimal,
    network: str = "mainnet",
    reference: str | None = None,
) -> str | None:
    """Wallet deep link for this rail, or ``None`` when the chain has no usable standard.

    ``reference`` is the invoice's Solana Pay reference pubkey. Passing it is what makes
    reference matching possible at all: the wallet attaches it to the transaction as a
    read-only account, and the watcher can then identify the payer's invoice outright
    instead of inferring it from the amount. Ignored on every non-Solana rail.
    """
    testnet = str(network).lower() == "testnet"

    if spec.chain in _EVM_CHAIN_IDS:
        mainnet_id, testnet_id = _EVM_CHAIN_IDS[spec.chain]
        chain_id = testnet_id if testnet else mainnet_id
        base_units = int(amount * (Decimal(10) ** spec.decimals))
        if spec.token_contract:
            return (
                f"ethereum:{spec.token_contract}@{chain_id}/transfer"
                f"?address={to_address}&uint256={base_units}"
            )
        return f"ethereum:{to_address}@{chain_id}?value={base_units}"

    if spec.chain in ("bitcoin", "litecoin"):
        return f"{spec.chain}:{to_address}?amount={_plain(amount)}"

    if spec.chain == "solana":
        uri = f"solana:{to_address}?amount={_plain(amount)}"
        if spec.token_mint:
            uri += f"&spl-token={spec.token_mint}"
        if reference:
            uri += f"&reference={reference}"
        return uri

    return None  # tron and anything else — caller shows the bare address


def qr_payload(
    *,
    spec: AssetSpec,
    to_address: str,
    amount: Decimal,
    network: str = "mainnet",
    reference: str | None = None,
) -> str:
    """What to encode in the QR: a wallet URI when one exists, else the bare address."""
    return (
        build_payment_uri(
            spec=spec,
            to_address=to_address,
            amount=amount,
            network=network,
            reference=reference,
        )
        or to_address
    )
