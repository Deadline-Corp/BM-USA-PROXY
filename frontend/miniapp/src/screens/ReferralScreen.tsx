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
import type { ReferralPayout, PayoutRail } from "../shared/api/types";
import { formatUsd } from "../shared/lib/format";
import { ErrorState } from "../shared/components/ErrorState";

// The bot accepts this prefix and the shorter `r_`. Changing it here without changing
// app/bot/handlers/start.py is how every referral bound nobody until 2026-08-11; there is
// a backend test pinning this exact string.
const REFERRAL_BOT_LINK_BASE = "https://t.me/BM_USA_Proxy_bot?start=ref_";

/** Commission copy states the rate the ledger actually applies, not a number typed once.
 *
 * The API sends it as a float, and JS prints 23.0 as "23" and 12.5 as "12.5" — both read
 * correctly with no formatting of our own.
 */
function withPct(template: string, pct: number): string {
  return template.replace("{pct}", String(pct));
}

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
  const [network, setNetwork] = useState("");

  // The rails we actually pay out on come from the API — offering a network we don't
  // support just produces a request the backend has to reject.
  const rails = referralQuery.data?.payout_rails ?? [];
  const selectedNetwork = network || rails[0]?.network || "";

  const link = referralQuery.data ? `${REFERRAL_BOT_LINK_BASE}${referralQuery.data.code}` : "";
  const available = referralQuery.data?.balances.available ?? 0;
  // threshold may be 0, but there's still nothing to withdraw at a zero balance
  const belowMin = available <= 0 || available < (referralQuery.data?.min_payout_usd ?? 0);

  async function handleShare() {
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(
      strings.referral.shareText,
    )}`;
    window.open(shareUrl, "_blank", "noopener,noreferrer");
  }

  async function handlePayoutSubmit() {
    try {
      await requestPayout.mutateAsync({ wallet_address: walletAddress, network: selectedNetwork });
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
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border border-accent/[.14] bg-accent/[.07] text-accent">
            <Users size={20} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <b className="block font-head text-[18px] font-extrabold leading-tight tracking-tight text-text">
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
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border border-accent/[.14] bg-accent/[.07] text-accent">
          <Users size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[18px] font-extrabold leading-tight tracking-tight text-text">
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
      <div className="flex flex-col gap-3.5 rounded-xl border border-border/60 bg-surface p-[18px] pb-4 shadow-highlight">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
            <Users size={20} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <div className="flex flex-col gap-0.5">
            <b className="font-head text-[16.5px] font-bold tracking-tight text-text">
              {withPct(strings.referral.programTitle, r.pct)}
            </b>
            <small className="text-[13px] leading-relaxed text-text-2">
              {withPct(strings.referral.programBody, r.pct)}
            </small>
          </div>
        </div>
        {/* The third tile is back, and this time it counts something. It used to be a
            literal `0` in the markup labelled "clicks", backed by no field anywhere, so it
            read zero for everyone forever — a dead number beside real money makes the real
            ones look doubtful too. What it shows now is arrivals at the bot through this
            link, not clicks on it: somebody who opens the link and never presses START
            stays invisible to us, so the label says "Opened" and does not promise more. */}
        <div className="grid grid-cols-3 gap-2">
          <div className="flex flex-col items-center gap-0.5 rounded border border-border bg-surface-2 px-2 pb-2 pt-2.5">
            <Num className="text-[19px] leading-none text-text">{r.link_opens}</Num>
            <span className="text-[11px] uppercase tracking-wide text-text-3">{strings.referral.opensLabel}</span>
          </div>
          <div className="flex flex-col items-center gap-0.5 rounded border border-border bg-surface-2 px-2 pb-2 pt-2.5">
            <Num className="text-[19px] leading-none text-text">{r.signups}</Num>
            <span className="text-[11px] uppercase tracking-wide text-text-3">{strings.referral.signupsLabel}</span>
          </div>
          <div className="flex flex-col items-center gap-0.5 rounded border border-border bg-surface-2 px-2 pb-2 pt-2.5">
            <Num className="text-[19px] leading-none text-accent">{formatUsd(r.balances.available + r.balances.hold)}</Num>
            <span className="text-[11px] uppercase tracking-wide text-text-3">{strings.referral.earnedLabel}</span>
          </div>
        </div>
      </div>

      {/* ── referral link ── */}
      <SectionLabel className="mt-[18px]">{strings.referral.yourLink}</SectionLabel>
      <div className="flex items-center gap-2">
        <div className="flex h-12 min-w-0 flex-1 items-center gap-2 rounded border border-border-2 bg-surface-2 px-3">
          <Link2 size={14} className="shrink-0 text-text-3" aria-hidden="true" />
          <Num className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[12.5px] text-text-2">
            {link.replace("https://", "")}
          </Num>
        </div>
        <Button className="h-12 shrink-0 px-3.5" onClick={() => copy(link)}>
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
        <div className="flex flex-col gap-1 rounded-lg border border-border/60 bg-surface p-3.5 pb-3 shadow-soft">
          <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-3">
            <Clock size={11} aria-hidden="true" />
            {strings.referral.holdLabel}
          </span>
          <Num className="mt-0.5 text-[26px] leading-tight tracking-tight text-text">{formatUsd(r.balances.hold)}</Num>
          <span className="text-[12px] leading-snug text-text-3">{strings.referral.holdNote}</span>
        </div>
        <div className="flex flex-col gap-1 rounded-lg border border-accent/[.36] bg-accent/[.07] p-3.5 pb-3">
          <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-2">
            <CheckCircle2 size={11} className="text-accent" aria-hidden="true" />
            {strings.referral.availableLabel}
          </span>
          <Num className="mt-0.5 text-[26px] leading-tight tracking-tight text-accent">
            {formatUsd(r.balances.available)}
          </Num>
          <span className="text-[12px] leading-snug text-text-3">{strings.referral.availableNote}</span>
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
        <p className="mt-1.5 text-center text-[12.5px] text-text-3">
          {strings.referral.payoutBelowMin} <Num>{formatUsd(r.min_payout_usd)}</Num>
        </p>
      ) : null}

      {payoutSheetOpen ? (
        <PayoutSheet
          onClose={() => setPayoutSheetOpen(false)}
          walletAddress={walletAddress}
          setWalletAddress={setWalletAddress}
          network={selectedNetwork}
          setNetwork={setNetwork}
          rails={rails}
          onSubmit={handlePayoutSubmit}
          pending={requestPayout.isPending}
        />
      ) : null}

      {/* ── payout history ──
          The screen used to end at the balance. A partner who filed a request watched the
          number drop to zero with nothing on the page to reconcile it against, which is
          indistinguishable from money going missing — reported that way on 2026-09-04. */}
      {(r.payouts ?? []).length > 0 ? (
        <>
          <SectionLabel className="mt-5">{strings.referral.payoutHistory}</SectionLabel>
          <div className="flex flex-col gap-1.5">
            {(r.payouts ?? []).map((p) => (
              <PayoutRow key={p.id} payout={p} />
            ))}
          </div>
        </>
      ) : null}

      {/* ── who they brought ──
          By earnings, because that is the question a partner has about a list of people
          they referred. Handles arrive already shortened to a tail from the server. */}
      {(r.referrals ?? []).length > 0 ? (
        <>
          <SectionLabel className="mt-5">{strings.referral.peopleBrought}</SectionLabel>
          <div className="flex flex-col gap-1.5">
            {(r.referrals ?? []).map((person, i) => (
              <div
                key={`${person.handle}-${i}`}
                className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-surface px-3.5 py-2.5"
              >
                <Num as="span" className="text-[13.5px] text-text-2">
                  {person.handle}
                </Num>
                <Num className="text-[14px] font-semibold text-text">
                  {formatUsd(person.earned_usd)}
                </Num>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** One filed request. The status is the point — "requested" is the state the partner could
 *  not see, and it is what tells them the money is queued rather than gone. */
function PayoutRow({ payout }: { payout: ReferralPayout }) {
  const tone = {
    requested: "text-warning",
    approved: "text-accent",
    paid: "text-success",
    rejected: "text-danger",
  }[payout.status];
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border/60 bg-surface px-3.5 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <Num className="text-[15px] font-semibold text-text">{formatUsd(payout.amount_usd)}</Num>
        <span className={`text-[12.5px] font-medium ${tone}`}>
          {strings.referral.payoutStatus[payout.status]}
        </span>
      </div>
      <div className="flex items-center justify-between gap-3 text-[12px] text-text-3">
        <span>{new Date(payout.requested_at).toLocaleDateString()}</span>
        <span className="uppercase">{payout.network}</span>
      </div>
      {payout.reject_reason ? (
        <p className="text-[12px] leading-snug text-danger">{payout.reject_reason}</p>
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
  rails: PayoutRail[];
  onSubmit: () => void;
  pending: boolean;
}

function PayoutSheet({ onClose, walletAddress, setWalletAddress, network, setNetwork, rails, onSubmit, pending }: PayoutSheetProps) {
  // `network` arrives already resolved to the rail that will be submitted, so the coin
  // shown below is the coin that will actually be sent.
  const selectedRail = rails.find((r) => r.network === network);

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
          <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor="wallet-address">
            {strings.referral.walletAddress}
          </label>
          <input
            id="wallet-address"
            className="h-12 w-full rounded border border-border bg-surface-2 px-3 font-mono text-[14px] text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
            value={walletAddress}
            onChange={(e) => setWalletAddress(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor="wallet-network">
            {strings.referral.network}
          </label>
          <select
            id="wallet-network"
            className="h-12 w-full rounded border border-border bg-surface-2 px-3 text-[15px] text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
            value={network}
            onChange={(e) => setNetwork(e.target.value)}
          >
            {rails.map((rail) => (
              <option key={rail.network} value={rail.network}>
                {rail.network_label}
              </option>
            ))}
          </select>
        </div>
        {/* The coin is shown, not chosen: every rail pays USDT, so a second dropdown would
            be a control with one option. Disabled rather than plain text so it reads as
            part of the same form — the person can see what they are getting and see that
            it is not theirs to pick. Comes from the selected rail, never hard-coded, so
            adding a non-USDT rail cannot make this line lie. */}
        <div>
          <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor="wallet-coin">
            {strings.referral.coin}
          </label>
          <input
            id="wallet-coin"
            readOnly
            disabled
            value={selectedRail?.asset ?? ""}
            className="h-12 w-full cursor-not-allowed rounded border border-border bg-surface px-3 text-[15px] text-text-2"
          />
        </div>
      </div>
    </Sheet>
  );
}
