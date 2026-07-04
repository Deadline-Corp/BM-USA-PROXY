import { useState } from "react";
import { Users, Link2, Send, Clock, CheckCircle2, Check, Copy } from "lucide-react";
import { useReferral, useRequestPayout } from "../shared/hooks/useReferral";
import { useMe } from "../shared/hooks/useMe";
import { useToast } from "../shared/components/Toast";
import { strings } from "../shared/strings";
import { SectionLabel } from "../shared/components/Card";
import { Button } from "../shared/components/Button";
import { Num } from "../shared/components/Num";
import { Sheet } from "../shared/components/Sheet";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { ApiError } from "../shared/api/client";
import { formatUsd } from "../shared/lib/format";
import { ErrorState } from "../shared/components/ErrorState";

const REFERRAL_BOT_LINK_BASE = "https://t.me/BM_USA_Proxy_bot?start=ref_";

function ReferralSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-40 animate-pulse rounded-xl bg-surface-2" />
      <div className="h-11 animate-pulse rounded bg-surface-2" />
      <div className="grid grid-cols-2 gap-2">
        <div className="h-24 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-24 animate-pulse rounded-lg bg-surface-2" />
      </div>
    </div>
  );
}

export function ReferralScreen() {
  const referralQuery = useReferral();
  const meQuery = useMe();
  const requestPayout = useRequestPayout();
  const { showToast } = useToast();
  const { copied, copy } = useCopyToClipboard();

  const [payoutSheetOpen, setPayoutSheetOpen] = useState(false);
  const [walletAddress, setWalletAddress] = useState("");
  const [network, setNetwork] = useState("TRC-20");

  const link = referralQuery.data ? `${REFERRAL_BOT_LINK_BASE}${referralQuery.data.code}` : "";
  const belowMin = referralQuery.data
    ? referralQuery.data.balances.available < referralQuery.data.min_payout_usd
    : true;

  async function handleShare() {
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(
      strings.referral.shareText,
    )}`;
    window.open(shareUrl, "_blank", "noopener,noreferrer");
  }

  async function handlePayoutSubmit() {
    try {
      await requestPayout.mutateAsync({ wallet_address: walletAddress, network });
      setPayoutSheetOpen(false);
      setWalletAddress("");
      showToast(strings.referral.payoutSent);
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : strings.errors.generic, "error");
    }
  }

  if (referralQuery.isLoading) {
    return (
      <div className="flex flex-col">
        <div className="mb-4 flex items-center gap-2.5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
            <Users size={20} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <b className="block font-head text-[15.5px] font-semibold leading-tight tracking-tight text-text">
              {strings.referral.title}
            </b>
          </div>
        </div>
        <ReferralSkeleton />
      </div>
    );
  }

  if (referralQuery.isError || !referralQuery.data) {
    return <ErrorState message={strings.errors.generic} onRetry={() => referralQuery.refetch()} />;
  }

  const r = referralQuery.data;

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
          <Users size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[15.5px] font-semibold leading-tight tracking-tight text-text">
            {strings.referral.title}
          </b>
        </div>
        {meQuery.data && meQuery.data.referral.available_usd > 0 ? (
          <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-[7px] text-xs text-text-2">
            <span>{strings.referral.availableLabel}</span>
            <Num className="text-[12.5px] font-medium text-text">{formatUsd(r.balances.available)}</Num>
          </div>
        ) : null}
      </div>

      {/* ── program hero ── */}
      <div className="flex flex-col gap-3.5 rounded-xl border border-border bg-surface p-[18px] pb-4 shadow-highlight">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-accent/[.22] bg-accent/[.13] text-accent">
            <Users size={18} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <div className="flex flex-col gap-0.5">
            <b className="font-head text-[15px] font-semibold tracking-tight text-text">{strings.referral.programTitle}</b>
            <small className="text-xs leading-relaxed text-text-2">{strings.referral.programBody}</small>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="flex flex-col items-center gap-0.5 rounded border border-border bg-surface-2 px-2 pb-2 pt-2.5">
            <Num className="text-[18px] leading-none text-text">{r.signups}</Num>
            <span className="text-[10px] uppercase tracking-wide text-text-3">{strings.referral.signupsLabel}</span>
          </div>
          <div className="flex flex-col items-center gap-0.5 rounded border border-border bg-surface-2 px-2 pb-2 pt-2.5">
            <Num className="text-[18px] leading-none text-text">0</Num>
            <span className="text-[10px] uppercase tracking-wide text-text-3">{strings.referral.clicksLabel}</span>
          </div>
          <div className="flex flex-col items-center gap-0.5 rounded border border-border bg-surface-2 px-2 pb-2 pt-2.5">
            <Num className="text-[18px] leading-none text-accent">{formatUsd(r.balances.available + r.balances.hold)}</Num>
            <span className="text-[10px] uppercase tracking-wide text-text-3">{strings.referral.earnedLabel}</span>
          </div>
        </div>
      </div>

      {/* ── referral link ── */}
      <SectionLabel className="mt-[18px]">{strings.referral.yourLink}</SectionLabel>
      <div className="flex items-center gap-2">
        <div className="flex h-11 min-w-0 flex-1 items-center gap-2 rounded border border-border-2 bg-surface-2 px-2.5">
          <Link2 size={13} className="shrink-0 text-text-3" aria-hidden="true" />
          <Num className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[11.5px] text-text-2">
            {link.replace("https://", "")}
          </Num>
        </div>
        <Button className="h-11 shrink-0 px-3.5" onClick={() => copy(link)}>
          {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
          {strings.common.copy}
        </Button>
      </div>

      <Button variant="primary" block className="mt-2" onClick={handleShare}>
        <Send size={16} aria-hidden="true" />
        {strings.referral.shareViaTelegram}
      </Button>

      {/* ── balances ── */}
      <SectionLabel className="mt-5">{strings.referral.balanceLabel}</SectionLabel>
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1 rounded-lg border border-border bg-surface p-3.5 pb-3">
          <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-text-3">
            <Clock size={11} aria-hidden="true" />
            {strings.referral.holdLabel}
          </span>
          <Num className="mt-0.5 text-[24px] leading-tight tracking-tight text-text">{formatUsd(r.balances.hold)}</Num>
          <span className="text-[11px] leading-snug text-text-3">{strings.referral.holdNote}</span>
        </div>
        <div className="flex flex-col gap-1 rounded-lg border border-accent/[.36] bg-accent/[.07] p-3.5 pb-3">
          <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-text-2">
            <CheckCircle2 size={11} className="text-accent" aria-hidden="true" />
            {strings.referral.availableLabel}
          </span>
          <Num className="mt-0.5 text-[24px] leading-tight tracking-tight text-accent">
            {formatUsd(r.balances.available)}
          </Num>
          <span className="text-[11px] leading-snug text-text-3">{strings.referral.availableNote}</span>
        </div>
      </div>

      <Button
        variant="primary"
        block
        className="mt-2.5"
        disabled={belowMin}
        onClick={() => setPayoutSheetOpen(true)}
      >
        {strings.referral.requestPayout} — <Num>{formatUsd(r.balances.available)}</Num>
      </Button>
      {belowMin ? (
        <p className="mt-1.5 text-center text-[11.5px] text-text-3">
          {strings.referral.payoutBelowMin} <Num>{formatUsd(r.min_payout_usd)}</Num>
        </p>
      ) : null}

      {payoutSheetOpen ? (
        <PayoutSheet
          onClose={() => setPayoutSheetOpen(false)}
          walletAddress={walletAddress}
          setWalletAddress={setWalletAddress}
          network={network}
          setNetwork={setNetwork}
          onSubmit={handlePayoutSubmit}
          pending={requestPayout.isPending}
        />
      ) : null}
    </div>
  );
}

interface PayoutSheetProps {
  onClose: () => void;
  walletAddress: string;
  setWalletAddress: (v: string) => void;
  network: string;
  setNetwork: (v: string) => void;
  onSubmit: () => void;
  pending: boolean;
}

function PayoutSheet({ onClose, walletAddress, setWalletAddress, network, setNetwork, onSubmit, pending }: PayoutSheetProps) {
  return (
    <Sheet
      open
      onClose={onClose}
      title={strings.referral.payoutFormTitle}
      footer={
        <Button variant="primary" block disabled={walletAddress.trim().length === 0 || pending} onClick={onSubmit}>
          {strings.common.submit}
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-text-2" htmlFor="wallet-address">
            {strings.referral.walletAddress}
          </label>
          <input
            id="wallet-address"
            className="h-11 w-full rounded border border-border bg-surface-2 px-3 font-mono text-[13px] text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
            value={walletAddress}
            onChange={(e) => setWalletAddress(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-text-2" htmlFor="wallet-network">
            {strings.referral.network}
          </label>
          <select
            id="wallet-network"
            className="h-11 w-full rounded border border-border bg-surface-2 px-3 text-sm text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
            value={network}
            onChange={(e) => setNetwork(e.target.value)}
          >
            <option value="TRC-20">USDT · TRC-20</option>
            <option value="ERC-20">USDT · ERC-20</option>
            <option value="BTC">BTC</option>
            <option value="ETH">ETH</option>
          </select>
        </div>
      </div>
    </Sheet>
  );
}
