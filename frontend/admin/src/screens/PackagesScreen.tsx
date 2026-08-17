import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge, formatStatusLabel } from "@/shared/components/StatusBadge";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { FilterBar } from "@/shared/components/TableFilters";
import { DateFilterPill, FilterPill } from "@/shared/components/FilterPill";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Modal } from "@/shared/components/Modal";
import { OrderNumber } from "@/shared/components/OrderNumber";
import { formatDate } from "@/shared/lib/format";
import {
  useAccessesList,
  useExtendAccess,
  useReissueAccess,
  useRevokeAccess,
  useSetAutoRotate,
} from "@/shared/hooks/useAccesses";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { AccessRow } from "@/shared/api/types";
import { IconRotate } from "@/shared/components/icons";

// No one-shot "rotate" here on purpose: rotating an IP is the buyer's action, taken from
// their own app. An operator doing it from the console changed a live customer's address
// under them with no way for that customer to know why. Setting the *schedule* stays —
// "make it rotate every 30 minutes" is a thing customers ask support for.
type ActionKind = "revoke" | "extend" | "reissue" | "autoRotate";

/** Every state an access can be in — the same list the database constraint allows. */
const STATUSES = ["provisioning", "active", "expiring", "expired", "revoked", "failed"];

export function PackagesScreen() {
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [expiringOnly, setExpiringOnly] = useState(false);
  const [since, setSince] = useState("");
  const [before, setBefore] = useState("");
  const { limit, offset, setOffset } = usePagination();
  const q = useDebouncedValue(search.trim());

  const [actionTarget, setActionTarget] = useState<{ row: AccessRow; kind: ActionKind } | null>(null);
  const [extendMinutes, setExtendMinutes] = useState(60);
  const [autoRotateMinutes, setAutoRotateMinutes] = useState(30);

  const revokeMutation = useRevokeAccess();
  const extendMutation = useExtendAccess();
  const autoRotateMutation = useSetAutoRotate();
  const reissueMutation = useReissueAccess();

  useEffect(() => {
    setOffset(0);
  }, [q, status, expiringOnly, since, before, setOffset]);

  const params = useMemo(
    () => ({
      limit,
      offset,
      ...(q ? { q } : {}),
      ...(status ? { status } : {}),
      ...(expiringOnly ? { expiring: true } : {}),
      ...(since ? { since } : {}),
      ...(before ? { before } : {}),
    }),
    [q, status, expiringOnly, since, before, limit, offset],
  );

  const isFiltered = Boolean(q || status || expiringOnly || since || before);
  const clearAll = () => {
    setSearch("");
    setStatus("");
    setExpiringOnly(false);
    setSince("");
    setBefore("");
  };

  const { data, isLoading, isError, refetch } = useAccessesList(params);

  function openAction(row: AccessRow, kind: ActionKind) {
    setExtendMinutes(60);
    // Opens on whatever this access already runs, so "every 45 minutes" doesn't silently
    // become 30 because the dialog reset to its default.
    setAutoRotateMinutes(row.auto_rotate_minutes ?? 30);
    setActionTarget({ row, kind });
  }
  function closeAction() {
    setActionTarget(null);
  }

  async function handleRevoke(reason?: string) {
    if (!actionTarget) return;
    try {
      await revokeMutation.mutateAsync({ id: actionTarget.row.id, reason: reason ?? "" });
      toast.success("Access revoked");
      closeAction();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleExtend() {
    if (!actionTarget) return;
    try {
      await extendMutation.mutateAsync({ id: actionTarget.row.id, minutes: extendMinutes });
      toast.success("Access extended");
      closeAction();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleAutoRotate(enabled: boolean) {
    if (!actionTarget) return;
    try {
      await autoRotateMutation.mutateAsync({
        id: actionTarget.row.id,
        enabled,
        minutes: enabled ? autoRotateMinutes : null,
      });
      toast.success(enabled ? "Auto-rotation set" : "Auto-rotation off");
      closeAction();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleReissue() {
    if (!actionTarget) return;
    try {
      await reissueMutation.mutateAsync({ id: actionTarget.row.id });
      toast.success("Access reissued");
      closeAction();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  const columns = useMemo<ColumnDef<AccessRow, any>[]>(
    () => [
      {
        header: "User",
        accessorKey: "user",
        cell: ({ row }) => <span className="font-mono text-[.82rem] text-text">{row.original.user}</span>,
      },
      {
        header: strings.orders.colStatus,
        accessorKey: "status",
        cell: ({ row }) => {
          // The reason an operator was required to type on revoke, finally readable. It
          // was written to a column nothing ever selected, so "why did this customer lose
          // their proxy" could only be answered by asking whoever pressed the button.
          // Only for a revoke: expiry stamps revoked_at too, and a plain "Expired" badge
          // already says everything about time running out.
          const revoked = row.original.status === "revoked";
          const reason = row.original.revoke_reason;
          return (
            <div className="flex flex-col gap-0.5">
              <StatusBadge status={row.original.status} />
              {revoked && reason ? (
                <span
                  className="max-w-[190px] truncate text-[.72rem] text-text-3"
                  title={[
                    reason,
                    row.original.revoked_by ? `by ${row.original.revoked_by}` : null,
                    row.original.revoked_at ? formatDate(row.original.revoked_at) : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                >
                  {reason}
                </span>
              ) : null}
            </div>
          );
        },
      },
      {
        header: "City",
        accessorKey: "city",
        cell: ({ row }) => row.original.city ?? "—",
      },
      {
        header: "Carrier",
        accessorKey: "carrier",
        cell: ({ row }) => row.original.carrier ?? "—",
      },
      {
        // The phone behind the access. Named first because that is what the pool screen
        // shows; the id underneath is what the iproxy console takes.
        header: strings.packages.colConnection,
        accessorKey: "connection_id",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.connection_id ? (
            <span className="flex flex-col leading-tight">
              <span className="text-[.82rem] text-text">{row.original.connection_name ?? "—"}</span>
              <span className="font-mono text-[.7rem] text-text-3">{row.original.connection_id}</span>
            </span>
          ) : (
            "—"
          ),
      },
      {
        header: "IP",
        accessorKey: "ip",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{row.original.ip ?? "—"}</span>,
      },
      {
        header: "Plan",
        accessorKey: "tariff_code",
      },
      {
        // Which purchase paid for this proxy. Next to the tariff on purpose: together
        // they answer "what did they buy and on which order", which is the question a
        // support conversation opens with.
        header: strings.packages.colOrder,
        accessorKey: "order_number",
        enableSorting: false,
        cell: ({ row }) => <OrderNumber value={row.original.order_number} />,
      },
      {
        header: "Expires",
        accessorKey: "expires_at",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDate(row.original.expires_at)}</span>,
      },
      {
        header: strings.packages.colAutoRotate,
        accessorKey: "auto_rotate_minutes",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.auto_rotate_minutes ? (
            <span className="font-mono text-[.8rem]">{row.original.auto_rotate_minutes}m</span>
          ) : (
            <span className="text-text-3">{strings.common.off}</span>
          ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => {
          // An offered button is a claim that the action applies. On a revoked access
          // none of these three did: revoking again wrote a second "revoked" event for a
          // transition that never happened, extending moved the expiry of something still
          // unusable and told the customer it had been extended, and rotating reached
          // through to a connection that revocation had already freed — quite possibly
          // sold to someone else by then, whose live IP would change under them.
          // Each flag mirrors the matching guard in provisioning.lifecycle exactly, so a
          // greyed-out button means precisely "the API would refuse this" — no more and
          // no less. Guessing wider here quietly removes capability: revoking an expired
          // access is worth keeping, since it forces the provisioner-side cleanup.
          const status = row.original.status;
          const can = {
            // `expired` is extendable on purpose — the backend resurrects it.
            extend: !["revoked", "cancelled", "failed"].includes(status),
            // Only a live access has a schedule worth setting.
            autoRotate: status === "active" || status === "expiring",
            // Reissue is the way *back* from revoked, so it stays available there.
            reissue: true,
            revoke: status !== "revoked",
          };
          return (
            <div className="flex items-center gap-1.5 justify-end" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="quiet"
                size="sm"
                disabled={!can.extend}
                title={can.extend ? undefined : strings.packages.cannotExtend}
                onClick={() => openAction(row.original, "extend")}
              >
                {strings.packages.extend}
              </Button>
              <Button
                variant="quiet"
                size="sm"
                disabled={!can.autoRotate}
                title={can.autoRotate ? strings.packages.autoRotate : strings.packages.cannotAutoRotate}
                onClick={() => openAction(row.original, "autoRotate")}
              >
                <IconRotate className="w-3.5 h-3.5" />
              </Button>
              <Button variant="quiet" size="sm" onClick={() => openAction(row.original, "reissue")}>
                {strings.packages.reissue}
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={!can.revoke}
                title={can.revoke ? undefined : strings.packages.cannotRevoke}
                onClick={() => openAction(row.original, "revoke")}
              >
                {strings.packages.revoke}
              </Button>
            </div>
          );
        },
      },
    ],
    [],
  );

  return (
    <div>
      <PageHead title={strings.packages.title} subtitle={strings.packages.subtitle} />

      <Panel>
        <DataTable
          columns={columns}
          data={data?.items ?? []}
          total={data?.total ?? 0}
          limit={limit}
          offset={offset}
          onOffsetChange={setOffset}
          isLoading={isLoading}
          isError={isError}
          onRetry={refetch}
          getRowId={(row) => row.id}
          emptyTitle={isFiltered ? "Nothing matches these filters" : "No packages found"}
          emptyHint={isFiltered ? "Widen the date range, or clear the filters." : undefined}
          toolbar={
            <FilterBar
              search={search}
              onSearchChange={setSearch}
              searchPlaceholder={strings.packages.searchPlaceholder}
              isFiltered={isFiltered}
              onClear={clearAll}
            >
              <FilterPill
                label={strings.packages.filterStatus}
                value={status}
                onChange={setStatus}
                options={STATUSES.map((s) => ({ value: s, label: formatStatusLabel(s) }))}
                allLabel={strings.common.all}
              />
              <FilterPill
                label={strings.packages.filterExpiring}
                value={expiringOnly ? "soon" : ""}
                onChange={(v) => setExpiringOnly(v === "soon")}
                options={[{ value: "soon", label: "Within 24h" }]}
                allLabel={strings.common.all}
              />
              <DateFilterPill
                label={strings.common.filterFrom}
                value={since}
                onChange={setSince}
                anyLabel={strings.common.anyDate}
              />
              <DateFilterPill
                label={strings.common.filterTo}
                value={before}
                onChange={setBefore}
                anyLabel={strings.common.anyDate}
              />
            </FilterBar>
          }
        />
      </Panel>

      <ConfirmDialog
        open={actionTarget?.kind === "revoke"}
        onClose={closeAction}
        onConfirm={handleRevoke}
        title={strings.packages.revoke}
        description={strings.packages.revokeConfirm}
        confirmLabel={strings.packages.revoke}
        danger
        requireReason
        isSubmitting={revokeMutation.isPending}
      />

      <ConfirmDialog
        open={actionTarget?.kind === "reissue"}
        onClose={closeAction}
        onConfirm={handleReissue}
        title={strings.packages.reissue}
        description="Assign a new connection to this access?"
        confirmLabel={strings.packages.reissue}
        isSubmitting={reissueMutation.isPending}
      />

      <Modal
        open={actionTarget?.kind === "extend"}
        onClose={closeAction}
        title={strings.packages.extend}
        footer={
          <>
            <Button variant="ghost" onClick={closeAction}>
              {strings.common.cancel}
            </Button>
            <Button variant="primary" onClick={handleExtend} isLoading={extendMutation.isPending}>
              {strings.packages.extend}
            </Button>
          </>
        }
      >
        <Input
          type="number"
          min={1}
          label={strings.packages.extendMinutes}
          value={extendMinutes}
          onChange={(e) => setExtendMinutes(Number(e.target.value))}
        />
      </Modal>

      <Modal
        open={actionTarget?.kind === "autoRotate"}
        onClose={closeAction}
        title={strings.packages.autoRotate}
        footer={
          <>
            <Button variant="ghost" onClick={closeAction}>
              {strings.common.cancel}
            </Button>
            {/* Turning it off is its own action rather than a zero in the field: an
                interval of 0 has no meaning, and "off" should not have to be spelled. */}
            <Button
              variant="quiet"
              onClick={() => handleAutoRotate(false)}
              isLoading={autoRotateMutation.isPending}
            >
              {strings.packages.autoRotateOff}
            </Button>
            <Button
              variant="primary"
              onClick={() => handleAutoRotate(true)}
              isLoading={autoRotateMutation.isPending}
            >
              {strings.common.save}
            </Button>
          </>
        }
      >
        <Input
          type="number"
          min={1}
          max={1440}
          label={strings.packages.autoRotateMinutes}
          hint={strings.packages.autoRotateHint}
          value={autoRotateMinutes}
          onChange={(e) => setAutoRotateMinutes(Number(e.target.value))}
        />
      </Modal>
    </div>
  );
}
