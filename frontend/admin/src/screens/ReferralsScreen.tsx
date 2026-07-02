import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatCard, StatClusterRow } from "@/shared/components/StatCard";
import { StatusBadge } from "@/shared/components/StatusBadge";
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
  useReferralSettings,
  useReferralSummary,
  useRejectPayout,
  useUpdateReferralSettings,
} from "@/shared/hooks/useReferrals";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Payout, ReferralLedgerEntry, ReferralSettings } from "@/shared/api/types";
import { IconClients, IconMail, IconReferrals, IconWallet } from "@/shared/components/icons";
import { RequireRole } from "@/shared/auth/RequireRole";

export function ReferralsScreen() {
  const toast = useToast();
  const summaryQuery = useReferralSummary();
  const { limit, offset, setOffset } = usePagination();
  const ledgerParams = useMemo(() => ({ limit, offset }), [limit, offset]);
  const ledgerQuery = useReferralLedger(ledgerParams);
  const payoutsQuery = usePayouts("pending");
  const settingsQuery = useReferralSettings();
  const updateSettingsMutation = useUpdateReferralSettings();

  const approveMutation = useApprovePayout();
  const rejectMutation = useRejectPayout();
  const markPaidMutation = useMarkPayoutPaid();

  const [rejectTarget, setRejectTarget] = useState<Payout | null>(null);
  const [markPaidTarget, setMarkPaidTarget] = useState<Payout | null>(null);
  const [txHash, setTxHash] = useState("");

  const [settingsDraft, setSettingsDraft] = useState<Partial<ReferralSettings> | null>(null);
  const settings = settingsDraft ?? settingsQuery.data;

  async function handleApprove(id: string) {
    try {
      await approveMutation.mutateAsync(id);
      toast.success("Payout approved");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
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

  async function handleSaveSettings() {
    if (!settingsDraft) return;
    try {
      await updateSettingsMutation.mutateAsync(settingsDraft);
      toast.success("Referral settings saved");
      setSettingsDraft(null);
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

      <div className="grid grid-cols-[1.4fr_1fr] gap-4 max-[1100px]:grid-cols-1">
        <div className="flex flex-col gap-4">
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
              emptyTitle="No referral activity yet"
            />
          </Panel>

          <RequireRole role="owner">
            <Panel>
              <Panel.Head title={strings.referrals.settings} />
              <Panel.Body>
                {settingsQuery.isLoading || !settings ? (
                  <Skeleton className="h-24" />
                ) : (
                  <div className="flex flex-col gap-4">
                    <div className="grid grid-cols-3 gap-3">
                      <Input
                        type="number"
                        step="0.1"
                        label={strings.referrals.commissionPct}
                        value={settings.commission_pct ?? 0}
                        onChange={(e) => setSettingsDraft({ ...settings, commission_pct: Number(e.target.value) })}
                      />
                      <Input
                        type="number"
                        step="0.01"
                        label={strings.referrals.minPayoutUsd}
                        value={settings.min_payout_usd ?? 0}
                        onChange={(e) => setSettingsDraft({ ...settings, min_payout_usd: Number(e.target.value) })}
                      />
                      <Input
                        type="number"
                        label={strings.referrals.cookieDays}
                        value={settings.cookie_days ?? 0}
                        onChange={(e) => setSettingsDraft({ ...settings, cookie_days: Number(e.target.value) })}
                      />
                    </div>
                    {settingsDraft && (
                      <div className="flex justify-end">
                        <Button size="sm" variant="primary" onClick={handleSaveSettings} isLoading={updateSettingsMutation.isPending}>
                          {strings.common.save}
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </Panel.Body>
            </Panel>
          </RequireRole>
        </div>

        <Panel>
          <Panel.Head title={strings.referrals.payoutsQueue} subtitle={`${payoutsQuery.data?.total ?? 0} pending`} />
          <div className="flex flex-col">
            {payoutsQuery.isLoading ? (
              <Skeleton className="h-40 m-4" />
            ) : (payoutsQuery.data?.items.length ?? 0) === 0 ? (
              <EmptyState title="No pending payouts" />
            ) : (
              payoutsQuery.data?.items.map((p) => (
                <div key={p.id} className="flex items-center gap-3 px-[18px] py-3.5 border-b border-border last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[.82rem] text-text truncate">{p.referrer}</div>
                    <div className="text-[.76rem] text-text-3 mt-0.5">{formatDateTime(p.requested_at)}</div>
                  </div>
                  <Num value={p.amount_usd} usd className="text-[.9rem] font-semibold text-text flex-none" />
                  <div className="flex items-center gap-1.5 flex-none">
                    <Button variant="quiet" size="sm" onClick={() => setRejectTarget(p)}>
                      {strings.referrals.reject}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setMarkPaidTarget(p)}>
                      {strings.referrals.markPaid}
                    </Button>
                    <Button variant="primary" size="sm" onClick={() => handleApprove(p.id)} isLoading={approveMutation.isPending}>
                      {strings.referrals.approve}
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </Panel>
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
    </div>
  );
}
