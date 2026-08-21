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


# ── what may go in a QR, which is scanned by things that are not wallets ──
def _invoice(asset: str, network: str, address: str, amount: str):
    """Enough of an Invoice for the link helpers — they read five fields."""
    from app.models import Invoice

    return Invoice(
        provider="onchain",
        provider_invoice_id=f"t-{asset}-{network}",
        status="pending",
        amount_usd=10,
        crypto_currency=asset,
        crypto_network=network,
        crypto_amount=Decimal(amount),
        pay_address=address,
    )


def test_a_token_qr_never_leads_with_the_contract_address() -> None:
    """The one case where this is about losing money, not convenience.

    An EIP-681 token payment is a contract call, so the address after `ethereum:` is the
    TOKEN, not the payee. An exchange scanner reads the leading address and stops: Bybit
    refusing the code — which is what the client's operator hit — is the safe outcome, and
    an app that parsed it naively would withdraw the customer's USDT to the USDT contract,
    where it cannot be recovered. So the QR carries the address alone.
    """
    from app.services.payments.invoice_links import invoice_qr_code, invoice_pay_uri

    for asset, network in (("USDT", "erc20"), ("USDC", "erc20"), ("USDT", "bep20")):
        inv = _invoice(asset, network, ADDR_EVM, "4.003")
        uri = invoice_pay_uri(inv)
        assert uri is not None and uri.split(":")[1].split("@")[0].lower() != ADDR_EVM.lower(), (
            "this test is pointless unless the URI really does lead with the contract"
        )
        assert invoice_qr_code(inv) == ADDR_EVM


def test_a_qr_carries_the_amount_wherever_the_payee_comes_first() -> None:
    """Bitcoin, Litecoin and Solana put the recipient straight after the scheme, so an app
    that understands only addresses still reads the right destination and the amount simply
    rides along. One code then serves a wallet and an exchange both."""
    from app.services.payments.invoice_links import invoice_qr_code

    btc = invoice_qr_code(_invoice("BTC", "native", ADDR_BTC, "0.00042"))
    assert btc == f"bitcoin:{ADDR_BTC}?amount=0.00042"

    sol = invoice_qr_code(_invoice("SOL", "native", ADDR_SOL, "1.5"))
    assert sol is not None and sol.startswith(f"solana:{ADDR_SOL}?amount=1.5")


def test_a_rail_with_no_uri_standard_still_gets_a_scannable_qr() -> None:
    """Tron has no scheme the wallets honour, and the address alone is what everything
    reads — which is also the rail we point small payments at."""
    from app.services.payments.invoice_links import invoice_qr_code

    assert invoice_qr_code(_invoice("USDT", "trc20", ADDR_TRON, "4.003")) == ADDR_TRON


def test_the_wallet_deep_link_is_left_alone() -> None:
    """The button beside the code opens a wallet on this device, where the contract call is
    exactly right. Narrowing the QR must not narrow that too."""
    from app.services.payments.invoice_links import invoice_pay_uri

    uri = invoice_pay_uri(_invoice("USDT", "erc20", ADDR_EVM, "4.003"))
    assert uri is not None
    assert "/transfer?address=" in uri and "uint256=4003000" in uri
