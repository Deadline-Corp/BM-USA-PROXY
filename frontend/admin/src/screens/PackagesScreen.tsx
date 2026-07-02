import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Button } from "@/shared/components/Button";
import { Select } from "@/shared/components/form/Select";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { Input } from "@/shared/components/form/Input";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Modal } from "@/shared/components/Modal";
import { formatDate } from "@/shared/lib/format";
import { useAccessesList, useExtendAccess, useReissueAccess, useRevokeAccess, useRotateIp } from "@/shared/hooks/useAccesses";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { AccessRow } from "@/shared/api/types";
import { IconRotate } from "@/shared/components/icons";

type ActionKind = "revoke" | "extend" | "rotate" | "reissue";

export function PackagesScreen() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [city, setCity] = useState("");
  const [user, setUser] = useState("");
  const [expiringOnly, setExpiringOnly] = useState(false);
  const { limit, offset, setOffset, resetOffset } = usePagination();

  const [actionTarget, setActionTarget] = useState<{ row: AccessRow; kind: ActionKind } | null>(null);
  const [extendMinutes, setExtendMinutes] = useState(60);

  const revokeMutation = useRevokeAccess();
  const extendMutation = useExtendAccess();
  const rotateMutation = useRotateIp();
  const reissueMutation = useReissueAccess();

  const params = useMemo(
    () => ({
      status: status || undefined,
      city: city || undefined,
      user: user || undefined,
      expiring: expiringOnly || undefined,
      limit,
      offset,
    }),
    [status, city, user, expiringOnly, limit, offset],
  );

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
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5 justify-end" onClick={(e) => e.stopPropagation()}>
            <Button variant="quiet" size="sm" onClick={() => openAction(row.original, "extend")}>
              {strings.packages.extend}
            </Button>
            <Button variant="quiet" size="sm" onClick={() => openAction(row.original, "rotate")}>
              <IconRotate className="w-3.5 h-3.5" />
            </Button>
            <Button variant="quiet" size="sm" onClick={() => openAction(row.original, "reissue")}>
              {strings.packages.reissue}
            </Button>
            <Button variant="danger" size="sm" onClick={() => openAction(row.original, "revoke")}>
              {strings.packages.revoke}
            </Button>
          </div>
        ),
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
          emptyTitle="No packages found"
          toolbar={
            <div className="flex items-center gap-3 flex-wrap">
              <Select value={status} onChange={(e) => { setStatus(e.target.value); resetOffset(); }} className="min-w-[150px]">
                <option value="">{strings.packages.filterStatus}: {strings.common.all}</option>
                <option value="active">Active</option>
                <option value="expired">Expired</option>
                <option value="revoked">Revoked</option>
              </Select>
              <Input
                value={city}
                onChange={(e) => { setCity(e.target.value); resetOffset(); }}
                placeholder={strings.packages.filterCity}
                className="max-w-[160px]"
              />
              <Input
                value={user}
                onChange={(e) => { setUser(e.target.value); resetOffset(); }}
                placeholder={strings.packages.filterUser}
                className="max-w-[180px]"
              />
              <Checkbox
                id="expiring-only"
                label={strings.packages.filterExpiring}
                checked={expiringOnly}
                onChange={(e) => { setExpiringOnly(e.target.checked); resetOffset(); }}
              />
            </div>
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
