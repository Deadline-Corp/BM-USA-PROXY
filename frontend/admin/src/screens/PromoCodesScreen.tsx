import { useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { TableSkeleton } from "@/shared/components/Skeleton";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { IconPlus, IconTrash } from "@/shared/components/icons";
import { PromoFormModal } from "@/screens/promos/PromoFormModal";
import { PromoUsagePanel } from "@/screens/promos/PromoUsagePanel";
import { usePromoCodes, useDeletePromoCode } from "@/shared/hooks/usePromos";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { formatDate } from "@/shared/lib/format";
import { strings } from "@/shared/strings";
import type { PromoCode } from "@/shared/api/types";

/** The dates as one cell. Two columns of mostly-empty dates said less than one line. */
function windowLabel(p: PromoCode): string {
  if (!p.starts_at && !p.expires_at) return strings.promos.noExpiry;
  const from = p.starts_at ? formatDate(p.starts_at) : strings.promos.fromNow;
  const to = p.expires_at ? formatDate(p.expires_at) : strings.promos.noExpiry;
  return `${from} → ${to}`;
}

export function PromoCodesScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = usePromoCodes();
  const deleteMutation = useDeletePromoCode();

  const [formOpen, setFormOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<PromoCode | null>(null);

  const rows = data?.items ?? [];

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      toast.success(strings.promos.deleted);
      setDeleteTarget(null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead
        title={strings.promos.title}
        subtitle={strings.promos.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={() => setFormOpen(true)}>
            <IconPlus />
            {strings.promos.create}
          </Button>
        }
      />

      <div className="mb-4 rounded-lg border border-border bg-surface-2 px-[18px] py-3 text-[.8rem] text-text-2 leading-relaxed">
        {strings.promos.banner}
      </div>

      <Panel>
        {isLoading ? (
          <TableSkeleton cols={7} />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={strings.promos.empty}
            hint={strings.promos.emptyHint}
            action={
              <Button variant="ghost" size="sm" onClick={() => setFormOpen(true)}>
                {strings.promos.create}
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[.86rem]">
              <thead>
                <tr>
                  {[
                    strings.promos.code,
                    strings.promos.percentOff,
                    strings.promos.colWindow,
                    strings.promos.colUses,
                    strings.promos.appliesTo,
                    strings.promos.colState,
                    strings.promos.note,
                    "",
                  ].map((h, i) => (
                    <th
                      key={`${h}-${i}`}
                      className="text-left text-[.7rem] uppercase tracking-[.08em] text-text-3 font-semibold px-[14px] py-2.5 border-b border-border whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr
                    key={p.id}
                    className="border-b border-border last:border-b-0 hover:bg-surface-2 transition-colors duration-150 ease-brand"
                  >
                    <td className="px-[14px] py-3 font-mono text-[.82rem] text-text">{p.code}</td>
                    <td className="px-[14px] py-3 font-mono tabular-nums text-text">
                      {p.percent_off}%
                    </td>
                    <td className="px-[14px] py-3 text-text-2 whitespace-nowrap">
                      {windowLabel(p)}
                    </td>
                    {/* Used over allowed, in one cell: "3" on its own does not say whether
                        the code is nearly spent. */}
                    <td className="px-[14px] py-3 font-mono tabular-nums text-text-2 whitespace-nowrap">
                      {p.used} / {p.max_uses ?? "∞"}
                    </td>
                    <td className="px-[14px] py-3 text-text-2 whitespace-nowrap">
                      {p.applies_to === "purchase"
                        ? strings.promos.appliesToPurchase
                        : strings.promos.appliesToAny}
                    </td>
                    <td className="px-[14px] py-3">
                      <StatusBadge status={p.state} />
                    </td>
                    <td className="px-[14px] py-3 text-text-3 max-w-[220px] truncate" title={p.note ?? ""}>
                      {p.note || "—"}
                    </td>
                    <td className="px-[14px] py-3 text-right">
                      <Button
                        variant="quiet"
                        size="sm"
                        onClick={() => setDeleteTarget(p)}
                        aria-label={strings.common.delete}
                      >
                        <IconTrash />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* Below the codes, not on a screen of its own: "who used it" is the question an
          operator asks while looking at the code, and a second nav entry for it would be
          a place nobody thinks to go. */}
      <PromoUsagePanel codes={rows} />

      <PromoFormModal open={formOpen} onClose={() => setFormOpen(false)} />

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title={strings.promos.deleteTitle}
        // Says what survives, because "cannot be undone" next to a spent campaign reads as
        // "this will also undo the orders", and it will not.
        description={`${deleteTarget?.code} stops working straight away and leaves this list. Orders already bought with it keep the price they were bought at.`}
        confirmLabel={strings.promos.deleteConfirm}
        danger
        isSubmitting={deleteMutation.isPending}
      />
    </div>
  );
}
