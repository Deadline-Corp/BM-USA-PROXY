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

export function ReferralsScreen() {
  const toast = useToast();
  const summaryQuery = useReferralSummary();
  const { limit, offset, setOffset } = usePagination();

  // The queue and the ledger are two lists answering two questions, so they filter
  // separately — narrowing the payouts you are about to send should not also hide half
  // the commission history you are checking them against.
  const [payoutSearch, setPayoutSearch] = useState("");
  const [payoutSince, setPayoutSince] = useState("");
  const [payoutBefore, setPayoutBefore] = useState("");
  const [ledgerSearch, setLedgerSearch] = useState("");
  const [ledgerStatus, setLedgerStatus] = useState("");
  const [ledgerSince, setLedgerSince] = useState("");
  const [ledgerBefore, setLedgerBefore] = useState("");

  const payoutQ = useDebouncedValue(payoutSearch.trim());
  const ledgerQ = useDebouncedValue(ledgerSearch.trim());

  useEffect(() => {
    setOffset(0);
  }, [ledgerQ, ledgerStatus, ledgerSince, ledgerBefore, setOffset]);

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
      ...(payoutQ ? { q: payoutQ } : {}),
      ...(payoutSince ? { since: payoutSince } : {}),
      ...(payoutBefore ? { before: payoutBefore } : {}),
    }),
    [payoutQ, payoutSince, payoutBefore],
  );
  // no status → the API returns everything still open (requested + approved). Passing
  // "pending" here filtered on a status that doesn't exist, so the queue was always empty.
  const payoutsQuery = usePayouts(payoutParams);

  const payoutsFiltered = Boolean(payoutQ || payoutSince || payoutBefore);
  const clearPayouts = () => {
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
      { header: strings.orders.colStatus, accessorKey: "status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
      { header: strings.orders.colAmount, accessorKey: "amount_usd", cell: ({ row }) => <Num value={row.original.amount_usd} usd className="text-text" /> },
      { header: "Date", accessorKey: "created_at", cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDateTime(row.original.created_at)}</span> },
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
          <Panel.Head title={strings.referrals.payoutsQueue} subtitle={`${payoutsQuery.data?.total ?? 0} pending`} />
          <div className="px-[18px] py-3 border-b border-border">
            <FilterBar
              search={payoutSearch}
              onSearchChange={setPayoutSearch}
              searchPlaceholder={strings.referrals.payoutSearchPlaceholder}
              isFiltered={payoutsFiltered}
              onClear={clearPayouts}
            >
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
              <EmptyState title="No pending payouts" hint="Requests appear here as referrers ask to be paid." />
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
          <Panel.Head title={strings.referrals.ledger} />
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
