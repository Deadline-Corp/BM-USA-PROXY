import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatCard, StatClusterRow } from "@/shared/components/StatCard";
import { StatusBadge, formatStatusLabel } from "@/shared/components/StatusBadge";
import { FilterBar } from "@/shared/components/TableFilters";
import { DateFilterPill, FilterPill } from "@/shared/components/FilterPill";
import { Button } from "@/shared/components/Button";
import { Num } from "@/shared/components/Num";
import { CopyInline } from "@/shared/components/CopyInline";
import { Input } from "@/shared/components/form/Input";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Modal } from "@/shared/components/Modal";
import { Skeleton } from "@/shared/components/Skeleton";
import { EmptyState } from "@/shared/components/EmptyState";
import { formatDateTime } from "@/shared/lib/format";
import {
  useApprovePayout,
  useMarkPayoutPaid,
  usePayouts,
  useReferralLedger,
  useReferralSummary,
  useRejectPayout,
} from "@/shared/hooks/useReferrals";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Payout, ReferralLedgerEntry } from "@/shared/api/types";
import { IconClients, IconMail, IconReferrals, IconWallet } from "@/shared/components/icons";
import { PayoutInstructionModal } from "@/screens/referrals/PayoutInstructionModal";

/** Every state a commission row can hold — the database constraint's own list. */
const LEDGER_STATUSES = ["hold", "available", "requested", "paid", "reversed"];

/** What the payouts panel is showing. The empty value is the queue — the two states
 *  that still need an operator — and is what the endpoint returns when asked for nothing.
 *  "all" is history: every payout ever, newest first. */
const PAYOUT_VIEWS = [
  { value: "all", label: "All" },
  { value: "paid", label: "Sent" },
  { value: "rejected", label: "Rejected" },
];

/** Every state a payout can be in, for the history tab's filter. Unlike the queue above,
 *  the empty value here means all four — history's default is to hide nothing. */
const PAYOUT_HISTORY_STATUSES = ["requested", "approved", "paid", "rejected"];

export function ReferralsScreen() {
  const toast = useToast();
  const summaryQuery = useReferralSummary();
  const { limit, offset, setOffset } = usePagination();

  // The queue and the ledger are two lists answering two questions, so they filter
  // separately — narrowing the payouts you are about to send should not also hide half
  // the commission history you are checking them against.
  // "" is the open queue — what still needs somebody to act. The console had no way
  // to see a payout after it was sent, so a partner could quote a history from the
  // mini app that the operator could not find. Reported 2026-09-08.
  const [payoutStatus, setPayoutStatus] = useState("");
  const [payoutSearch, setPayoutSearch] = useState("");
  const [payoutSince, setPayoutSince] = useState("");
  const [payoutBefore, setPayoutBefore] = useState("");
  const [ledgerSearch, setLedgerSearch] = useState("");
  const [ledgerStatus, setLedgerStatus] = useState("");
  const [ledgerSince, setLedgerSince] = useState("");
  const [ledgerBefore, setLedgerBefore] = useState("");

  // Which question the lower panel answers. The ledger is commission earned, one row per
  // order; payouts are money that left, one row per withdrawal. They were never the same
  // list, and the queue above only holds what is still open — a payout disappeared from
  // the console the moment it was sent, so "who has taken out how much, and where to"
  // could not be answered here at all.
  const [historyView, setHistoryView] = useState<"ledger" | "payouts">("ledger");
  const [historySearch, setHistorySearch] = useState("");
  const [historyStatus, setHistoryStatus] = useState("");
  const [historySince, setHistorySince] = useState("");
  const [historyBefore, setHistoryBefore] = useState("");

  const payoutQ = useDebouncedValue(payoutSearch.trim());
  const ledgerQ = useDebouncedValue(ledgerSearch.trim());
  const historyQ = useDebouncedValue(historySearch.trim());

  // One offset serves both tabs, so switching them has to rewind it too — otherwise page
  // four of the ledger becomes an empty payouts table with a pager that disagrees.
  useEffect(() => {
    setOffset(0);
  }, [
    ledgerQ,
    ledgerStatus,
    ledgerSince,
    ledgerBefore,
    historyView,
    historyQ,
    historyStatus,
    historySince,
    historyBefore,
    setOffset,
  ]);

  const ledgerParams = useMemo(
    () => ({
      limit,
      offset,
      ...(ledgerQ ? { q: ledgerQ } : {}),
      ...(ledgerStatus ? { status: ledgerStatus } : {}),
      ...(ledgerSince ? { since: ledgerSince } : {}),
      ...(ledgerBefore ? { before: ledgerBefore } : {}),
    }),
    [limit, offset, ledgerQ, ledgerStatus, ledgerSince, ledgerBefore],
  );
  const ledgerQuery = useReferralLedger(ledgerParams);

  const payoutParams = useMemo(
    () => ({
      ...(payoutStatus ? { status: payoutStatus } : {}),
      ...(payoutQ ? { q: payoutQ } : {}),
      ...(payoutSince ? { since: payoutSince } : {}),
      ...(payoutBefore ? { before: payoutBefore } : {}),
    }),
    [payoutStatus, payoutQ, payoutSince, payoutBefore],
  );
  // no status → the API returns everything still open (requested + approved). Passing
  // "pending" here filtered on a status that doesn't exist, so the queue was always empty.
  const payoutsQuery = usePayouts(payoutParams);

  const historyParams = useMemo(
    () => ({
      // "all" is the whole history, deliberately: the endpoint's own default is the open
      // queue, which is the panel above this one.
      status: historyStatus || "all",
      ...(historyQ ? { q: historyQ } : {}),
      ...(historySince ? { since: historySince } : {}),
      ...(historyBefore ? { before: historyBefore } : {}),
    }),
    [historyStatus, historyQ, historySince, historyBefore],
  );
  const historyQuery = usePayouts(historyParams, { enabled: historyView === "payouts" });
  // /payouts answers with the whole result set — it is a history, not a feed — so the
  // page is cut here. Slicing what arrived keeps the pager honest about the total.
  const historyRows = historyQuery.data?.items ?? [];
  const historyPage = useMemo(
    () => historyRows.slice(offset, offset + limit),
    [historyRows, offset, limit],
  );
  const historyFiltered = Boolean(historyQ || historyStatus || historySince || historyBefore);
  const clearHistory = () => {
    setHistorySearch("");
    setHistoryStatus("");
    setHistorySince("");
    setHistoryBefore("");
  };

  const payoutsFiltered = Boolean(payoutStatus || payoutQ || payoutSince || payoutBefore);
  const clearPayouts = () => {
    setPayoutStatus("");
    setPayoutSearch("");
    setPayoutSince("");
    setPayoutBefore("");
  };
  const ledgerFiltered = Boolean(ledgerQ || ledgerStatus || ledgerSince || ledgerBefore);
  const clearLedger = () => {
    setLedgerSearch("");
    setLedgerStatus("");
    setLedgerSince("");
    setLedgerBefore("");
  };

  const approveMutation = useApprovePayout();
  const rejectMutation = useRejectPayout();
  const markPaidMutation = useMarkPayoutPaid();

  const [rejectTarget, setRejectTarget] = useState<Payout | null>(null);
  const [markPaidTarget, setMarkPaidTarget] = useState<Payout | null>(null);
  const [sendTarget, setSendTarget] = useState<string | null>(null);
  const [txHash, setTxHash] = useState("");


  /** Authorise the payout (if it still needs it), then show the transfer instructions.
   *
   * Approving and sending were two buttons for one decision — nobody approves a payout
   * they are not about to send. Merged, so the authorisation cannot be skipped by going
   * straight for the instructions; the watcher settles only approved payouts.
   */
  async function handleSend(p: Payout) {
    if (p.status === "requested") {
      try {
        await approveMutation.mutateAsync(p.id);
      } catch (err) {
        toast.error(apiErrorMessage(err));
        return; // no instructions for a payout we failed to authorise
      }
    }
    setSendTarget(p.id);
  }

  async function handleReject(reason?: string) {
    if (!rejectTarget) return;
    try {
      await rejectMutation.mutateAsync({ id: rejectTarget.id, reason: reason ?? "" });
      toast.success("Payout rejected");
      setRejectTarget(null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleMarkPaid() {
    if (!markPaidTarget || !txHash.trim()) return;
    try {
      await markPaidMutation.mutateAsync({ id: markPaidTarget.id, tx_hash: txHash.trim() });
      toast.success("Payout marked paid");
      setMarkPaidTarget(null);
      setTxHash("");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  const ledgerColumns = useMemo<ColumnDef<ReferralLedgerEntry, any>[]>(
    () => [
      { header: "Referrer", accessorKey: "referrer", cell: ({ row }) => <span className="font-mono text-[.8rem] text-text">{row.original.referrer}</span> },
      // The search box has always accepted a referral code; without the column you could
      // type one and had no way to see whether the rows that came back were the right ones.
      // Copyable, because the next thing you do with a code is paste it somewhere.
      { header: "Referral code", accessorKey: "referral_code", cell: ({ row }) => <CopyInline value={row.original.referral_code} /> },
      { header: strings.orders.colStatus, accessorKey: "status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
      { header: strings.orders.colAmount, accessorKey: "amount_usd", cell: ({ row }) => <Num value={row.original.amount_usd} usd className="text-text" /> },
      { header: "Date", accessorKey: "created_at", cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDateTime(row.original.created_at)}</span> },
    ],
    [],
  );

  const payoutColumns = useMemo<ColumnDef<Payout, any>[]>(
    () => [
      { header: "Referrer", accessorKey: "referrer", cell: ({ row }) => <span className="font-mono text-[.8rem] text-text">{row.original.referrer}</span> },
      { header: strings.orders.colStatus, accessorKey: "status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
      { header: strings.orders.colAmount, accessorKey: "amount_usd", cell: ({ row }) => <Num value={row.original.amount_usd} usd className="text-text" /> },
      // The coin, not the network id: "trc20" says where it went, "USDT TRC-20 (Tron)"
      // says what was sent, and the client reads this column to answer the second.
      { header: strings.referrals.colCoin, accessorKey: "rail_label", cell: ({ row }) => <span className="text-[.8rem] text-text-2">{row.original.rail_label}</span> },
      { header: strings.referrals.colWallet, accessorKey: "wallet_address", cell: ({ row }) => <CopyInline value={row.original.wallet_address} /> },
      { header: strings.referrals.colTx, accessorKey: "tx_hash", cell: ({ row }) => <CopyInline value={row.original.tx_hash} /> },
      // Dated by when the money left. A payout still in the queue has no such moment yet,
      // so it falls back to when it was asked for rather than showing an empty cell.
      {
        header: "Date",
        accessorKey: "processed_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem]">
            {formatDateTime(row.original.processed_at ?? row.original.requested_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div>
      <PageHead title={strings.referrals.title} subtitle={strings.referrals.subtitle} />

      {summaryQuery.isLoading ? (
        <Skeleton className="h-24 rounded-lg mb-5" />
      ) : (
        <StatClusterRow className="grid-cols-2 min-[900px]:!grid-cols-5 mb-5">
          <StatCard icon={<IconClients />} label={strings.referrals.totalReferrers} value={<Num value={summaryQuery.data?.total_referrers ?? 0} />} />
          <StatCard icon={<IconReferrals />} label={strings.referrals.totalClicks} value={<Num value={summaryQuery.data?.total_clicks ?? 0} />} />
          <StatCard icon={<IconClients />} label={strings.referrals.totalAttached} value={<Num value={summaryQuery.data?.total_attached ?? 0} />} />
          <StatCard icon={<IconWallet />} label={strings.referrals.totalPaid} value={<Num value={summaryQuery.data?.total_paid_usd ?? 0} usd />} />
          <StatCard icon={<IconMail />} label={strings.referrals.pendingPayouts} value={<Num value={summaryQuery.data?.pending_payouts ?? 0} />} />
        </StatClusterRow>
      )}

      {/* Stacked, queue first. Side by side, the queue was a narrow column of work next to
          a wide column of history — and the work is what the operator opens this screen
          for. Full width also lets a payout row breathe: who, when, how much, and the
          three buttons no longer fight for the same 400px. */}
      <div className="flex flex-col gap-4">
        <Panel>
          <Panel.Head title={strings.referrals.payoutsQueue} subtitle={`${payoutsQuery.data?.total ?? 0} ${payoutStatus ? "shown" : "pending"}`} />
          <div className="px-[18px] py-3 border-b border-border">
            <FilterBar
              search={payoutSearch}
              onSearchChange={setPayoutSearch}
              searchPlaceholder={strings.referrals.payoutSearchPlaceholder}
              isFiltered={payoutsFiltered}
              onClear={clearPayouts}
            >
              <FilterPill
                label={strings.orders.colStatus}
                value={payoutStatus}
                onChange={setPayoutStatus}
                options={PAYOUT_VIEWS}
                allLabel={strings.referrals.payoutViewOpen}
              />
              <DateFilterPill
                label={strings.common.filterFrom}
                value={payoutSince}
                onChange={setPayoutSince}
                anyLabel={strings.common.anyDate}
              />
              <DateFilterPill
                label={strings.common.filterTo}
                value={payoutBefore}
                onChange={setPayoutBefore}
                anyLabel={strings.common.anyDate}
              />
            </FilterBar>
          </div>
          <div className="flex flex-col">
            {payoutsQuery.isLoading ? (
              <Skeleton className="h-40 m-4" />
            ) : (payoutsQuery.data?.items.length ?? 0) === 0 ? (
              // Not the default "try adjusting your filters" — this queue has no filters,
              // and an empty one is the normal, good state.
              <EmptyState title={strings.referrals.noPendingPayouts} hint={strings.referrals.noPendingPayoutsHint} />
            ) : (
              payoutsQuery.data?.items.map((p) => (
                <div key={p.id} className="flex items-center gap-3 px-[18px] py-3.5 border-b border-border last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[.82rem] text-text truncate">{p.referrer}</div>
                    <div className="text-[.76rem] text-text-3 mt-0.5">{formatDateTime(p.requested_at)}</div>
                  </div>
                  {/* Fixed width and right-aligned so amounts stack into a readable column
                      instead of drifting with the button row's width. */}
                  <Num value={p.amount_usd} usd className="text-[.9rem] font-semibold text-text flex-none w-[110px] text-right" />
                  <div className="flex items-center gap-1.5 flex-none">
                    <Button variant="quiet" size="sm" onClick={() => setRejectTarget(p)}>
                      {strings.referrals.reject}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setMarkPaidTarget(p)}>
                      {strings.referrals.markPaid}
                    </Button>
                    {/* One button, not Approve-then-Send. Approving and then sending were
                        always the same decision; splitting them only invited skipping the
                        first, and the watcher settles nothing that is not approved. */}
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleSend(p)}
                      isLoading={approveMutation.isPending}
                    >
                      {strings.referrals.send}
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </Panel>

        <Panel>
          <Panel.Head
            title={historyView === "payouts" ? strings.referrals.tabPayouts : strings.referrals.ledger}
            subtitle={
              historyView === "payouts" ? (
                <>
                  {historyQuery.data?.total ?? 0} {strings.referrals.payoutsCounted} ·{" "}
                  <Num value={historyQuery.data?.paid_amount_usd ?? 0} usd /> {strings.referrals.payoutsSent}
                </>
              ) : undefined
            }
            actions={
              <div className="flex items-center gap-1 bg-surface-2 border border-border rounded-lg p-1">
                <TabButton active={historyView === "ledger"} onClick={() => setHistoryView("ledger")}>
                  {strings.referrals.tabLedger}
                </TabButton>
                <TabButton active={historyView === "payouts"} onClick={() => setHistoryView("payouts")}>
                  {strings.referrals.tabPayouts}
                </TabButton>
              </div>
            }
          />
          {historyView === "payouts" ? (
            <DataTable
              columns={payoutColumns}
              data={historyPage}
              total={historyRows.length}
              limit={limit}
              offset={offset}
              onOffsetChange={setOffset}
              isLoading={historyQuery.isLoading}
              isError={historyQuery.isError}
              onRetry={historyQuery.refetch}
              getRowId={(row) => row.id}
              emptyTitle={historyFiltered ? "Nothing matches these filters" : strings.referrals.noPayouts}
              emptyHint={
                historyFiltered ? "Widen the date range, or clear the filters." : strings.referrals.noPayoutsHint
              }
              toolbar={
                <FilterBar
                  search={historySearch}
                  onSearchChange={setHistorySearch}
                  searchPlaceholder={strings.referrals.payoutsHistorySearchPlaceholder}
                  isFiltered={historyFiltered}
                  onClear={clearHistory}
                >
                  <FilterPill
                    label={strings.orders.colStatus}
                    value={historyStatus}
                    onChange={setHistoryStatus}
                    options={PAYOUT_HISTORY_STATUSES.map((s) => ({ value: s, label: formatStatusLabel(s) }))}
                    allLabel={strings.common.all}
                  />
                  <DateFilterPill
                    label={strings.common.filterFrom}
                    value={historySince}
                    onChange={setHistorySince}
                    anyLabel={strings.common.anyDate}
                  />
                  <DateFilterPill
                    label={strings.common.filterTo}
                    value={historyBefore}
                    onChange={setHistoryBefore}
                    anyLabel={strings.common.anyDate}
                  />
                </FilterBar>
              }
            />
          ) : (
            <DataTable
              columns={ledgerColumns}
              data={ledgerQuery.data?.items ?? []}
              total={ledgerQuery.data?.total ?? 0}
              limit={limit}
              offset={offset}
              onOffsetChange={setOffset}
              isLoading={ledgerQuery.isLoading}
              isError={ledgerQuery.isError}
              onRetry={ledgerQuery.refetch}
              getRowId={(row) => row.id}
              emptyTitle={ledgerFiltered ? "Nothing matches these filters" : "No referral activity yet"}
              emptyHint={ledgerFiltered ? "Widen the date range, or clear the filters." : undefined}
              toolbar={
                <FilterBar
                  search={ledgerSearch}
                  onSearchChange={setLedgerSearch}
                  searchPlaceholder={strings.referrals.ledgerSearchPlaceholder}
                  isFiltered={ledgerFiltered}
                  onClear={clearLedger}
                >
                  <FilterPill
                    label={strings.orders.colStatus}
                    value={ledgerStatus}
                    onChange={setLedgerStatus}
                    options={LEDGER_STATUSES.map((s) => ({ value: s, label: formatStatusLabel(s) }))}
                    allLabel={strings.common.all}
                  />
                  <DateFilterPill
                    label={strings.common.filterFrom}
                    value={ledgerSince}
                    onChange={setLedgerSince}
                    anyLabel={strings.common.anyDate}
                  />
                  <DateFilterPill
                    label={strings.common.filterTo}
                    value={ledgerBefore}
                    onChange={setLedgerBefore}
                    anyLabel={strings.common.anyDate}
                  />
                </FilterBar>
              }
            />
          )}
        </Panel>

        {/* The referral settings panel used to sit under the ledger, editing the same three
            keys the Settings screen already edits. Two editors for one value is how they
            end up disagreeing about which one is authoritative. Settings owns them now, in
            a panel of their own named after this screen. */}
      </div>

      <ConfirmDialog
        open={rejectTarget !== null}
        onClose={() => setRejectTarget(null)}
        onConfirm={handleReject}
        title={strings.referrals.reject}
        description="Reject this payout request?"
        danger
        requireReason
        isSubmitting={rejectMutation.isPending}
      />

      <Modal
        open={markPaidTarget !== null}
        onClose={() => {
          setMarkPaidTarget(null);
          setTxHash("");
        }}
        title={strings.referrals.markPaid}
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setMarkPaidTarget(null);
                setTxHash("");
              }}
            >
              {strings.common.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={handleMarkPaid}
              disabled={!txHash.trim()}
              isLoading={markPaidMutation.isPending}
            >
              {strings.referrals.markPaid}
            </Button>
          </>
        }
      >
        <Input
          label="Transaction hash"
          value={txHash}
          onChange={(e) => setTxHash(e.target.value)}
          placeholder="0x…"
        />
      </Modal>

      <PayoutInstructionModal payoutId={sendTarget} onClose={() => setSendTarget(null)} />
    </div>
  );
}

/** Same segmented control the Orders and Payments screens use — copied rather than shared,
 *  as they copy it from each other. Three copies is where it should become one component;
 *  doing that here would edit two screens this change has no business touching. */
function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "px-3.5 py-1.5 rounded-md text-[.82rem] font-semibold transition-colors duration-150 ease-brand flex items-center " +
        (active ? "bg-surface text-text shadow-sm" : "text-text-2 hover:text-text")
      }
    >
      {children}
    </button>
  );
}
