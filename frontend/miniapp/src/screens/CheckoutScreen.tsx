import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ShieldCheck,
  Clock,
  ArrowUpRight,
  Bell,
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
import { formatUsd } from "../shared/lib/format";
import { readCachedInvoice } from "../shared/lib/invoiceCache";
import type { OrderStatus } from "../shared/api/types";

// QR-style placeholder — hand-rolled 9x9 grid matching the demo's hand-drawn
// finder-pattern matrix (not a real QR code, purely decorative per spec).
function QrPlaceholder() {
  const pattern = [
    ["ac", "ac", "ac", "ac", "", "ac", "ac", "ac", "ac"],
    ["ac", "", "", "ac", "on", "ac", "", "", "ac"],
    ["ac", "", "hi", "ac", "", "ac", "hi", "", "ac"],
    ["ac", "ac", "ac", "ac", "hi", "ac", "ac", "ac", "ac"],
    ["", "hi", "", "hi", "ac", "hi", "", "hi", ""],
    ["ac", "ac", "ac", "ac", "on", "ac", "hi", "", "on"],
    ["ac", "", "hi", "ac", "", "on", "ac", "hi", "ac"],
    ["ac", "", "", "ac", "hi", "ac", "", "", "ac"],
    ["ac", "ac", "ac", "ac", "", "ac", "ac", "ac", "ac"],
  ];
  const cellClass: Record<string, string> = {
    ac: "bg-accent",
    hi: "bg-text",
    on: "bg-text-2",
    "": "bg-border",
  };
  return (
    <div
      className="grid h-[82px] w-[82px] shrink-0 grid-cols-9 grid-rows-9 gap-[1.5px] overflow-hidden rounded-[8px] border-[1.5px] border-border-2 bg-white p-1.5"
      role="img"
      aria-label="Payment QR code placeholder"
    >
      {pattern.flat().map((cell, i) => (
        <div key={i} className={`rounded-[1px] ${cellClass[cell]}`} />
      ))}
    </div>
  );
}

function truncateMiddle(value: string, head = 8, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
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

export function CheckoutScreen() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const orderQuery = useOrderStatus(orderId);
  const cancelOrder = useCancelOrder(orderId);
  const mockPay = useMockPay(orderId);
  // GET /orders/{id} does not return invoice payment details — only the
  // POST /orders response does. We cache that once at order-creation time
  // (see shared/lib/invoiceCache.ts) and read it back here.
  const [invoice] = useState(() => (orderId ? readCachedInvoice(orderId) : null));

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

  const meta = STATUS_META[orderQuery.data.status];
  const StatusIcon = meta.icon;

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

      {/* ── status card ── */}
      <div
        className={`flex flex-col items-center gap-3 rounded-lg border p-6 text-center ${
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
          className={`flex h-12 w-12 items-center justify-center rounded-full ${
            meta.tone === "success"
              ? "bg-success/10 text-success"
              : meta.tone === "danger"
                ? "bg-danger/10 text-danger"
                : meta.tone === "warning"
                  ? "bg-warning/10 text-warning"
                  : "bg-accent/10 text-accent"
          }`}
        >
          <StatusIcon size={22} className={meta.icon === Loader2 ? "animate-spin" : undefined} />
        </span>
        <div>
          <b className="block font-head text-[16px] font-semibold tracking-tight text-text">{meta.title}</b>
          {meta.body ? (
            <p className="mt-1 max-w-[260px] text-[13px] leading-relaxed text-text-2">{meta.body}</p>
          ) : null}
        </div>
      </div>

      {/* ── invoice details (only while awaiting payment, and only if we have a cached invoice) ── */}
      {orderQuery.data.status === "awaiting_payment" && invoice ? (
        <>
          <div className="mt-4 overflow-hidden rounded-lg border border-border bg-surface shadow-highlight">
            <div className="flex items-start justify-between gap-3 border-b border-border p-4">
              <div className="flex flex-col gap-1">
                <span className="flex items-baseline gap-1">
                  <Num className="text-[20px] font-bold leading-none text-text">
                    {invoice.crypto_amount !== null ? invoice.crypto_amount.toFixed(6) : "—"}
                  </Num>
                  <span className="text-[13px] font-medium text-text-3">{invoice.crypto_currency ?? ""}</span>
                </span>
                <span className="text-xs text-text-3">
                  {strings.checkout.amountApprox} <Num>{formatUsd(invoice.amount_usd)}</Num> USD
                  {invoice.crypto_network ? ` · ${invoice.crypto_network}` : ""}
                </span>
              </div>
              <QrPlaceholder />
            </div>

            {invoice.pay_address ? <PayAddressRow address={invoice.pay_address} /> : null}

            <div className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="relative h-2.5 w-2.5">
                  <span className="absolute -inset-1 animate-pulse2 rounded-full bg-warning/20" />
                  <span className="absolute inset-[1.5px] rounded-full bg-warning" />
                </span>
                <span className="text-[12.5px] font-semibold text-text-2">{strings.checkout.waitingForPayment}</span>
              </div>
              <Chip tone="warn">
                <CountdownBadge expiresAt={invoice.expires_at} valueClassName="text-[16px] text-warning" />
              </Chip>
            </div>
          </div>

          <div className="mt-3 flex items-start gap-2.5 rounded border border-accent/[.22] bg-accent/[.06] px-3.5 py-3">
            <Bell size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
            <p className="text-[12.5px] leading-relaxed text-text-2">
              <b className="text-text">{strings.checkout.autoDeliveredTitle}</b> — {strings.checkout.autoDeliveredBody}
            </p>
          </div>

          <div className="mt-3 flex flex-col gap-2">
            {invoice.payment_url ? (
              <a href={invoice.payment_url} target="_blank" rel="noopener noreferrer">
                <Button variant="primary" block>
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
