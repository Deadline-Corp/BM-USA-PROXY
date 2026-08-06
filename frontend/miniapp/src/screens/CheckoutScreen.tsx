import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import QRCode from "qrcode";
import {
  ShieldCheck,
  Clock,
  ArrowUpRight,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Check,
  Copy,
} from "lucide-react";
import { useOrderStatus, useCancelOrder, useMockPay } from "../shared/hooks/useOrder";
import { strings } from "../shared/strings";
import { Chip } from "../shared/components/Chip";
import { Button } from "../shared/components/Button";
import { Num } from "../shared/components/Num";
import { CountdownBadge } from "../shared/components/CountdownBadge";
import { ErrorState } from "../shared/components/ErrorState";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { formatCryptoAmount, formatUsd } from "../shared/lib/format";
import { isMobilePlatform, isWalletDeepLink } from "../shared/lib/platform";
import { readCachedInvoice } from "../shared/lib/invoiceCache";
import type { OrderStatus } from "../shared/api/types";

/**
 * Real, scannable payment QR.
 *
 * This used to be a hand-drawn 9x9 grid copied from the demo mock — it looked exactly
 * like a QR but encoded nothing, so buyers scanned it, got nothing, and lost trust at the
 * one screen where trust matters most. Renders the wallet deep link the backend built
 * (EIP-681 / BIP-21 / Solana Pay), falling back to the bare address on chains with no
 * standard. Nothing is drawn until we actually have a payload.
 */
function PaymentQr({ payload }: { payload: string | null }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (!payload) {
      setSrc(null);
      return;
    }
    QRCode.toDataURL(payload, { margin: 1, width: 240, errorCorrectionLevel: "M" })
      .then((url) => {
        if (alive) setSrc(url);
      })
      .catch(() => {
        if (alive) setSrc(null);
      });
    return () => {
      alive = false;
    };
  }, [payload]);

  if (!src) {
    // Deliberately blank rather than decorative: a fake QR is worse than none.
    return <div className="h-[82px] w-[82px] shrink-0 rounded-[8px] border-[1.5px] border-border-2 bg-surface-2" />;
  }
  return (
    <img
      src={src}
      alt="Payment QR code"
      className="h-[82px] w-[82px] shrink-0 rounded-[8px] border-[1.5px] border-border-2 bg-white p-1"
    />
  );
}

function truncateMiddle(value: string, head = 8, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/**
 * The exact amount, with its own copy button.
 *
 * Rendered straight from the API string. Retyping this by hand is the single easiest way
 * for a buyer to lose money here — one wrong digit and the deposit matches no invoice —
 * so copying it must be one tap, exactly like the address.
 */
function PayAmountRow({ amount, currency }: { amount: string | null; currency: string | null }) {
  const { copied, copy } = useCopyToClipboard();
  // Trailing zeros are dropped for both display and copy: "30.603405" is the same number
  // as "30.603405000000", and a wall of zeros on a pay-exactly-this screen reads as noise.
  const shown = formatCryptoAmount(amount);
  return (
    <span className="flex items-baseline gap-1.5">
      <Num className="text-[20px] font-bold leading-none text-text">{shown}</Num>
      <span className="text-[13px] font-medium text-text-3">{currency ?? ""}</span>
      {amount ? (
        <button
          type="button"
          className="ml-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center self-center rounded-[6px] border border-border-2 bg-transparent text-text-3 transition-colors duration-150 ease-out hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          aria-label="Copy exact amount"
          onClick={() => copy(shown)}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </button>
      ) : null}
    </span>
  );
}

function PayAddressRow({ address }: { address: string }) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
      <span className="w-9 shrink-0 text-[11px] font-semibold text-text-3">
        {strings.checkout.payAddressLabel}
      </span>
      <Num
        as="span"
        className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[11.5px] text-text-2"
      >
        {truncateMiddle(address)}
      </Num>
      <button
        type="button"
        className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[8px] border border-border-2 bg-transparent text-text-3 transition-colors duration-150 ease-out hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        aria-label="Copy payment address"
        onClick={() => copy(address)}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

const STATUS_META: Record<
  OrderStatus,
  { icon: typeof CheckCircle2; title: string; body: string; tone: "success" | "warning" | "danger" | "accent" }
> = {
  awaiting_payment: {
    icon: Clock,
    title: strings.checkout.waitingForPayment,
    body: "",
    tone: "warning",
  },
  confirming: {
    icon: Loader2,
    title: strings.checkout.confirming,
    body: "Your payment was detected on-chain — waiting for enough confirmations.",
    tone: "accent",
  },
  provisioning: {
    icon: Loader2,
    title: strings.checkout.provisioning,
    body: "Your device is being assigned. This usually takes a few seconds.",
    tone: "accent",
  },
  completed: {
    icon: CheckCircle2,
    title: strings.checkout.completedTitle,
    body: strings.checkout.completedBody,
    tone: "success",
  },
  expired: {
    icon: XCircle,
    title: strings.checkout.expiredTitle,
    body: strings.checkout.expiredBody,
    tone: "danger",
  },
  manual_review: {
    icon: AlertTriangle,
    title: strings.checkout.manualReviewTitle,
    body: strings.checkout.manualReviewBody,
    tone: "warning",
  },
  cancelled: {
    icon: XCircle,
    title: strings.checkout.cancelledTitle,
    body: strings.checkout.cancelledBody,
    tone: "danger",
  },
};

/** Deposit seen on-chain, not yet deep enough to release the proxy. */
const CONFIRMING_META = {
  icon: Loader2,
  title: strings.checkout.seenOnChainTitle,
  body: strings.checkout.seenOnChainBody,
  tone: "accent" as const,
};

export function CheckoutScreen() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const orderQuery = useOrderStatus(orderId);
  const cancelOrder = useCancelOrder(orderId);
  const mockPay = useMockPay(orderId);
  // GET /orders/{id} does not return invoice payment details — only the
  // POST /orders response does. We cache that once at order-creation time
  // (see shared/lib/invoiceCache.ts) and read it back here.
  // The API is the source of truth; the sessionStorage copy is only a first-paint
  // fallback. Relying on the cache alone meant a closed tab lost the address, the exact
  // amount and any way back into a payment that was already sent.
  const [cachedInvoice] = useState(() => (orderId ? readCachedInvoice(orderId) : null));
  // Buyer pressed "I've paid". Purely a UI acknowledgement — detection is automatic.
  const [claimedPaid, setClaimedPaid] = useState(false);

  const status = orderQuery.data?.status;
  const isTerminal = status ? ["completed", "expired", "manual_review", "cancelled"].includes(status) : false;

  if (orderQuery.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-14 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-44 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-20 animate-pulse rounded-lg bg-surface-2" />
      </div>
    );
  }

  if (orderQuery.isError || !orderQuery.data) {
    return <ErrorState message={strings.errors.orderNotFound} onRetry={() => orderQuery.refetch()} />;
  }

  const invoice = orderQuery.data.invoice ?? cachedInvoice;

  // The order sits at awaiting_payment until the deposit is final, so the order status
  // alone cannot tell "nothing has arrived" from "arrived, waiting on the chain". The
  // invoice status can, and that middle state is the whole point of this screen: without
  // it the buyer sends money and the screen says "waiting for payment" as if nothing
  // happened.
  const seenOnChain =
    orderQuery.data.status === "awaiting_payment" &&
    orderQuery.data.invoice_status === "confirming";
  const meta = seenOnChain ? CONFIRMING_META : STATUS_META[orderQuery.data.status];
  const StatusIcon = meta.icon;
  const stillAwaiting = orderQuery.data.status === "awaiting_payment";
  // The countdown belongs to "we are waiting for your money" and nothing else — leaving it
  // running after the deposit lands suggests the payment could still time out. It cannot:
  // a matched invoice is no longer expired by the sweeper.
  const showCountdown = stillAwaiting && !seenOnChain && Boolean(invoice?.expires_at);
  const showWalletLink = isMobilePlatform() && isWalletDeepLink(invoice?.pay_uri);

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
          <ShieldCheck size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[15.5px] font-semibold leading-tight tracking-tight text-text">
            {strings.checkout.title}
          </b>
          <span className="text-xs text-text-3">{strings.checkout.subtitle}</span>
        </div>
      </div>

      {/* ── status bar ──
          Horizontal and compact rather than a tall centred hero: the whole payment flow
          has to fit on one phone screen, and the countdown sits here — beside the state it
          belongs to — instead of being repeated further down. ── */}
      <div
        className={`flex items-center gap-3 rounded-lg border px-4 py-3.5 ${
          meta.tone === "success"
            ? "border-success/30 bg-success/[.05]"
            : meta.tone === "danger"
              ? "border-danger/30 bg-danger/[.05]"
              : meta.tone === "warning"
                ? "border-warning/30 bg-warning/[.05]"
                : "border-accent/30 bg-accent/[.05]"
        }`}
      >
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
            meta.tone === "success"
              ? "bg-success/10 text-success"
              : meta.tone === "danger"
                ? "bg-danger/10 text-danger"
                : meta.tone === "warning"
                  ? "bg-warning/10 text-warning"
                  : "bg-accent/10 text-accent"
          }`}
        >
          <StatusIcon size={18} className={meta.icon === Loader2 ? "animate-spin" : undefined} />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[14.5px] font-semibold leading-tight tracking-tight text-text">
            {meta.title}
          </b>
          {meta.body ? (
            <p className="mt-0.5 text-[12px] leading-snug text-text-2">{meta.body}</p>
          ) : null}
        </div>
        {showCountdown && invoice ? (
          <Chip tone="warn">
            <CountdownBadge expiresAt={invoice.expires_at} valueClassName="text-[15px] text-warning" />
          </Chip>
        ) : null}
      </div>

      {/* ── invoice details (only while awaiting payment, and only if we have a cached invoice) ── */}
      {orderQuery.data.status === "awaiting_payment" && invoice ? (
        <>
          <div className="mt-4 overflow-hidden rounded-lg border border-border bg-surface shadow-highlight">
            <div className="flex items-start justify-between gap-3 border-b border-border p-4">
              <div className="flex flex-col gap-1">
                {/* Rendered verbatim from the API string — never reformatted. The watcher
                    matches this amount to the last digit. */}
                <PayAmountRow amount={invoice.crypto_amount} currency={invoice.crypto_currency} />
                <span className="text-xs text-text-3">
                  {strings.checkout.amountApprox} <Num>{formatUsd(invoice.amount_usd)}</Num> USD
                  {invoice.crypto_network ? ` · ${invoice.crypto_network}` : ""}
                </span>
              </div>
              {/* Caption matters more than it looks: with Telegram open on a desktop the
                  QR is the only comfortable way to pay, and nothing on screen said so. */}
              <div className="flex shrink-0 flex-col items-center gap-1">
                <PaymentQr payload={invoice.pay_uri} />
                {invoice.pay_uri ? (
                  <span className="max-w-[86px] text-center text-[10px] leading-tight text-text-3">
                    {strings.checkout.qrHint}
                  </span>
                ) : null}
              </div>
            </div>

            {invoice.pay_address ? <PayAddressRow address={invoice.pay_address} /> : null}
          </div>

          {/* Actions disappear once the deposit is on-chain: "I've sent it" is answered by
              the status bar above, and cancelling would orphan money already sent — the
              order is still `awaiting_payment` at that point, so the endpoint would happily
              take it. */}
          {!seenOnChain ? (
            <div className="mt-3 flex flex-col gap-2">
              {/* Mobile only, and only where the chain has a link standard. The OS scheme
                  registry is what opens the wallet; on desktop nothing claims `ethereum:`
                  and the tap would do nothing at all. Tron has no standard, so the backend
                  hands back a bare address there and this stays hidden. */}
              {showWalletLink && invoice.pay_uri ? (
                <a href={invoice.pay_uri} rel="noopener noreferrer">
                  <Button variant="primary" block>
                    {strings.checkout.openInWallet}
                    <ArrowUpRight size={15} aria-hidden="true" />
                  </Button>
                </a>
              ) : null}
              <Button
                variant="primary"
                block
                disabled={claimedPaid}
                onClick={() => {
                  setClaimedPaid(true);
                  void orderQuery.refetch();
                }}
              >
                {claimedPaid ? strings.checkout.iHavePaidWaiting : strings.checkout.iHavePaid}
              </Button>
              {invoice.payment_url ? (
                <a href={invoice.payment_url} target="_blank" rel="noopener noreferrer">
                  <Button variant="default" block>
                    {strings.checkout.payInWallet}
                    <ArrowUpRight size={15} aria-hidden="true" />
                  </Button>
                </a>
              ) : null}
              {import.meta.env.DEV ? (
                <Button variant="ghost" block disabled={mockPay.isPending} onClick={() => mockPay.mutate()}>
                  {strings.checkout.simulatePayment}
                </Button>
              ) : null}
              <Button
                variant="ghost"
                block
                className="text-text-3"
                disabled={cancelOrder.isPending}
                onClick={() => cancelOrder.mutate()}
              >
                {strings.checkout.cancelAndGoBack}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}

      {/* ── fallback: awaiting payment but the invoice cache is empty (e.g. a
          reload lost sessionStorage, or the URL was opened directly) — still
          give the user a way out instead of a dead-end screen. ── */}
      {orderQuery.data.status === "awaiting_payment" && !invoice ? (
        <div className="mt-4 flex flex-col gap-2">
          <Button
            variant="ghost"
            block
            className="text-text-3"
            disabled={cancelOrder.isPending}
            onClick={() => cancelOrder.mutate()}
          >
            {strings.checkout.cancelAndGoBack}
          </Button>
        </div>
      ) : null}

      {/* ── terminal state actions ── */}
      {isTerminal ? (
        <div className="mt-4">
          {orderQuery.data.status === "completed" && orderQuery.data.access_public_id ? (
            <Button variant="primary" block onClick={() => navigate(`/access/${orderQuery.data!.access_public_id}`)}>
              {strings.checkout.openAccess}
            </Button>
          ) : orderQuery.data.status === "expired" || orderQuery.data.status === "cancelled" ? (
            <Button variant="default" block onClick={() => navigate("/catalog")}>
              {strings.checkout.retryToCatalog}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
