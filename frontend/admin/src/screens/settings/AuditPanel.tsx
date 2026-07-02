import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { Input } from "@/shared/components/form/Input";
import { formatDateTime } from "@/shared/lib/format";
import { useAuditLog } from "@/shared/hooks/useSystem";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { AuditLogEntry } from "@/shared/api/types";

export function AuditPanel() {
  const [entity, setEntity] = useState("");
  const [admin, setAdmin] = useState("");
  const { limit, offset, setOffset, resetOffset } = usePagination();

  const params = useMemo(
    () => ({ entity: entity || undefined, admin: admin || undefined, limit, offset }),
    [entity, admin, limit, offset],
  );
  const { data, isLoading, isError, refetch } = useAuditLog(params);

  const columns = useMemo<ColumnDef<AuditLogEntry, any>[]>(
    () => [
      { header: "Admin", accessorKey: "admin", cell: ({ row }) => <span className="font-mono text-[.8rem] text-text">{row.original.admin}</span> },
      { header: "Entity", accessorKey: "entity" },
      { header: "Action", accessorKey: "action" },
      { header: "When", accessorKey: "created_at", cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDateTime(row.original.created_at)}</span> },
    ],
    [],
  );

  return (
    <Panel>
      <Panel.Head title={strings.settings.audit} />
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
        emptyTitle="No audit entries"
        toolbar={
          <div className="flex items-center gap-3">
            <Input
              value={entity}
              onChange={(e) => {
                setEntity(e.target.value);
                resetOffset();
              }}
              placeholder="Filter by entity…"
              className="max-w-[200px]"
            />
            <Input
              value={admin}
              onChange={(e) => {
                setAdmin(e.target.value);
                resetOffset();
              }}
              placeholder="Filter by admin…"
              className="max-w-[200px]"
            />
          </div>
        }
      />
    </Panel>
  );
}
