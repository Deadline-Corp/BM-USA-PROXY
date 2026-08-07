"""Wallet deep links behind the payment QR — chain ids and amount encoding."""

from __future__ import annotations

from decimal import Decimal

from app.services.payments.onchain.assets import get_spec
from app.services.payments.onchain.payment_uri import build_payment_uri, qr_payload

ADDR_EVM = "0x1111111111111111111111111111111111111111"
ADDR_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
ADDR_BTC = "tb1qexampleexampleexampleexampleexample"
ADDR_SOL = "So11111111111111111111111111111111111111112"


def test_evm_chain_id_follows_the_network() -> None:
    """The whole point of the guard: a testnet QR must NOT open the wallet on mainnet.

    The buyer has real funds on mainnet. A deep link carrying chain id 1 while we run on
    Sepolia invites a real-money transfer during a test.
    """
    spec = get_spec("USDC", "erc20")
    main = build_payment_uri(spec=spec, to_address=ADDR_EVM, amount=Decimal("10"), network="mainnet")
    test = build_payment_uri(spec=spec, to_address=ADDR_EVM, amount=Decimal("10"), network="testnet")
    assert main is not None and "@1/" in main
    assert test is not None and "@11155111/" in test

    bsc = get_spec("USDT", "bep20")
    assert "@56/" in (build_payment_uri(spec=bsc, to_address=ADDR_EVM, amount=Decimal("1")) or "")
    testnet_bsc = build_payment_uri(
        spec=bsc, to_address=ADDR_EVM, amount=Decimal("1"), network="testnet"
    )
    assert testnet_bsc is not None and "@97/" in testnet_bsc


def test_evm_token_uses_transfer_and_base_units() -> None:
    spec = get_spec("USDT", "erc20")  # 6 decimals
    uri = build_payment_uri(spec=spec, to_address=ADDR_EVM, amount=Decimal("10.005"))
    assert uri == (
        f"ethereum:{spec.token_contract}@1/transfer?address={ADDR_EVM}&uint256=10005000"
    )


def test_evm_native_uses_value_in_wei() -> None:
    spec = get_spec("ETH", "native")  # 18 decimals
    uri = build_payment_uri(spec=spec, to_address=ADDR_EVM, amount=Decimal("0.5"))
    assert uri == f"ethereum:{ADDR_EVM}@1?value={5 * 10**17}"


def test_utxo_uses_bip21_with_whole_coins() -> None:
    uri = build_payment_uri(
        spec=get_spec("BTC", "native"), to_address=ADDR_BTC, amount=Decimal("0.00012345")
    )
    assert uri == f"bitcoin:{ADDR_BTC}?amount=0.00012345"


def test_small_amounts_never_use_exponent_notation() -> None:
    """Decimal('1E-8') would serialise as '1E-8' and no wallet parses that."""
    uri = build_payment_uri(
        spec=get_spec("BTC", "native"), to_address=ADDR_BTC, amount=Decimal("0.00000001")
    )
    assert uri is not None and "E" not in uri and uri.endswith("amount=0.00000001")


def test_solana_names_the_mint_for_token_payments() -> None:
    spl = get_spec("USDC", "spl")
    uri = build_payment_uri(spec=spl, to_address=ADDR_SOL, amount=Decimal("25"))
    assert uri is not None
    assert uri.startswith(f"solana:{ADDR_SOL}?amount=25")
    assert f"spl-token={spl.token_mint}" in uri

    native = build_payment_uri(
        spec=get_spec("SOL", "native"), to_address=ADDR_SOL, amount=Decimal("1.5")
    )
    assert native == f"solana:{ADDR_SOL}?amount=1.5"


def test_tron_has_no_standard_and_falls_back_to_the_address() -> None:
    spec = get_spec("USDT", "trc20")
    assert build_payment_uri(spec=spec, to_address=ADDR_TRON, amount=Decimal("10")) is None
    # the QR still has to show something scannable
    assert qr_payload(spec=spec, to_address=ADDR_TRON, amount=Decimal("10")) == ADDR_TRON


def test_solana_carries_the_invoice_reference() -> None:
    """Without this parameter nothing else in the reference chain can work.

    The wallet only attaches the reference pubkey to the transaction if the deep link asks
    for it. Omit it and the watcher has nothing to recognise, so matching silently falls
    back to the amount — which is exactly the ambiguity the reference exists to remove.
    """
    ref = "Ref1111111111111111111111111111111111111111"
    spl = get_spec("USDC", "spl")
    uri = build_payment_uri(
        spec=spl, to_address=ADDR_SOL, amount=Decimal("25"), reference=ref
    )
    assert uri is not None and f"reference={ref}" in uri

    native = build_payment_uri(
        spec=get_spec("SOL", "native"), to_address=ADDR_SOL, amount=Decimal("1.5"), reference=ref
    )
    assert native == f"solana:{ADDR_SOL}?amount=1.5&reference={ref}"

    # and it survives the QR wrapper the checkout screen actually calls
    assert f"reference={ref}" in qr_payload(
        spec=spl, to_address=ADDR_SOL, amount=Decimal("25"), reference=ref
    )


def test_non_solana_rails_ignore_the_reference() -> None:
    """A reference is a Solana Pay concept. Appending it elsewhere would corrupt the URI."""
    ref = "Ref1111111111111111111111111111111111111111"
    evm = build_payment_uri(
        spec=get_spec("USDC", "erc20"), to_address=ADDR_EVM, amount=Decimal("10"), reference=ref
    )
    btc = build_payment_uri(
        spec=get_spec("BTC", "native"), to_address=ADDR_BTC, amount=Decimal("0.01"), reference=ref
    )
    assert evm is not None and "reference" not in evm
    assert btc is not None and "reference" not in btc
