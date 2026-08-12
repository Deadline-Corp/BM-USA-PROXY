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
import { formatDate } from "@/shared/lib/format";
import { useAccessesList, useExtendAccess, useReissueAccess, useRevokeAccess, useRotateIp } from "@/shared/hooks/useAccesses";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { AccessRow } from "@/shared/api/types";
import { IconRotate } from "@/shared/components/icons";

type ActionKind = "revoke" | "extend" | "rotate" | "reissue";

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

  const revokeMutation = useRevokeAccess();
  const extendMutation = useExtendAccess();
  const rotateMutation = useRotateIp();
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

  async function handleRotate() {
    if (!actionTarget) return;
    try {
      await rotateMutation.mutateAsync(actionTarget.row.id);
      toast.success("IP rotated");
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
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
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
        header: "IP",
        accessorKey: "ip",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{row.original.ip ?? "—"}</span>,
      },
      {
        header: "Tariff",
        accessorKey: "tariff_code",
      },
      {
        header: "Expires",
        accessorKey: "expires_at",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDate(row.original.expires_at)}</span>,
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
          const live = status === "active" || status === "expiring";
          const can = {
            // `expired` is extendable on purpose — the backend resurrects it.
            extend: !["revoked", "cancelled", "failed"].includes(status),
            rotate: live,
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
                disabled={!can.rotate}
                title={can.rotate ? strings.packages.rotateIp : strings.packages.cannotRotate}
                onClick={() => openAction(row.original, "rotate")}
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
        open={actionTarget?.kind === "rotate"}
        onClose={closeAction}
        onConfirm={handleRotate}
        title={strings.packages.rotateIp}
        description={strings.packages.rotateIpConfirm}
        confirmLabel={strings.packages.rotateIp}
        isSubmitting={rotateMutation.isPending}
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
    </div>
  );
}
