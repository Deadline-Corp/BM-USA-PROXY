import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { FilterBar } from "@/shared/components/TableFilters";
import { DateFilterPill } from "@/shared/components/FilterPill";
import { formatAuditAction, formatAuditEntity, formatDateTime } from "@/shared/lib/format";
import { useAuditLog } from "@/shared/hooks/useSystem";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { AuditLogEntry } from "@/shared/api/types";

export function AuditPanel() {
  const [search, setSearch] = useState("");
  const [since, setSince] = useState("");
  const [before, setBefore] = useState("");
  const { limit, offset, setOffset } = usePagination();
  const q = useDebouncedValue(search.trim());

  useEffect(() => {
    setOffset(0);
  }, [q, since, before, setOffset]);

  const params = useMemo(
    () => ({
      limit,
      offset,
      ...(q ? { q } : {}),
      ...(since ? { since } : {}),
      ...(before ? { before } : {}),
    }),
    [limit, offset, q, since, before],
  );
  const { data, isLoading, isError, refetch } = useAuditLog(params);

  const isFiltered = Boolean(q || since || before);
  const clearAll = () => {
    setSearch("");
    setSince("");
    setBefore("");
  };

  const columns = useMemo<ColumnDef<AuditLogEntry, any>[]>(
    () => [
      {
        header: "Admin",
        accessorKey: "admin",
        cell: ({ row }) => <span className="text-text">{row.original.admin}</span>,
      },
      {
        // `app_setting` and `access.revoke` were printed as stored. They are keys, not
        // sentences — reading the log meant translating punctuation in your head.
        header: "Entity",
        accessorKey: "entity",
        cell: ({ row }) => <span className="text-text">{formatAuditEntity(row.original.entity)}</span>,
      },
      {
        header: "Action",
        accessorKey: "action",
        cell: ({ row }) => formatAuditAction(row.original.action),
      },
      {
        header: "When",
        accessorKey: "created_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem] whitespace-nowrap">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
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
        emptyTitle={isFiltered ? "Nothing matches these filters" : "No audit entries"}
        emptyHint={isFiltered ? "Widen the date range, or clear the filters." : undefined}
        toolbar={
          <FilterBar
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.settings.auditSearchPlaceholder}
            isFiltered={isFiltered}
            onClear={clearAll}
          >
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
  );
}
