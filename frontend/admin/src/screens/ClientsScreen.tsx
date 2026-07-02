import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { initials, formatDate } from "@/shared/lib/format";
import { useClientsList } from "@/shared/hooks/useClients";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { Client } from "@/shared/api/types";
import { ClientDossier } from "@/screens/clients/ClientDossier";
import { IconSearch } from "@/shared/components/icons";

export function ClientsScreen() {
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [hasActive, setHasActive] = useState(false);
  const [bannedOnly, setBannedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { limit, offset, setOffset, resetOffset } = usePagination();

  const params = useMemo(
    () => ({
      q: query || undefined,
      has_active: hasActive || undefined,
      banned: bannedOnly || undefined,
      limit,
      offset,
    }),
    [query, hasActive, bannedOnly, limit, offset],
  );

  const { data, isLoading, isError, refetch } = useClientsList(params);

  const columns = useMemo<ColumnDef<Client, any>[]>(
    () => [
      {
        header: strings.clients.colClient,
        accessorKey: "display_name",
        cell: ({ row }) => {
          const c = row.original;
          return (
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 flex-none rounded-lg bg-surface-2 border border-border-2 grid place-items-center font-mono text-[.7rem] font-semibold text-accent">
                {initials(c.display_name)}
              </div>
              <div className="min-w-0">
                <div className="text-text font-medium truncate">{c.display_name ?? "Unnamed"}</div>
                <div className="font-mono text-[.78rem] text-text-3 truncate">
                  {c.telegram_username ? `@${c.telegram_username}` : c.telegram_id}
                </div>
              </div>
            </div>
          );
        },
      },
      {
        header: strings.clients.colStatus,
        accessorKey: "banned",
        cell: ({ row }) =>
          row.original.banned ? (
            <StatusBadge tone="danger" label={strings.clients.banned} />
          ) : (
            <StatusBadge tone="success" label={strings.common.active} />
          ),
      },
      {
        header: strings.clients.colAccess,
        accessorKey: "has_active_access",
        cell: ({ row }) =>
          row.original.has_active_access ? (
            <StatusBadge tone="accent" label="Has access" />
          ) : (
            <StatusBadge tone="neutral" label="No access" />
          ),
      },
      {
        header: strings.clients.colJoined,
        accessorKey: "created_at",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDate(row.original.created_at)}</span>,
      },
    ],
    [],
  );

  return (
    <div>
      <PageHead title={strings.clients.title} subtitle={strings.clients.subtitle} />

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
          onRowClick={(row) => setSelectedId(row.id)}
          getRowId={(row) => row.id}
          emptyTitle="No clients found"
          emptyHint="Try a different search or clear filters."
          toolbar={
            <div className="flex items-center gap-3 flex-wrap">
              <div className="relative flex-1 min-w-[220px] max-w-[360px]">
                <IconSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-3 pointer-events-none" />
                <input
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    resetOffset();
                  }}
                  placeholder={strings.clients.searchPlaceholder}
                  className="w-full h-10 pl-9 pr-3 bg-surface-2 border border-border rounded-lg text-text text-[.86rem] focus:outline-none focus:border-accent-line transition-colors duration-150 ease-brand"
                />
              </div>
              <Checkbox
                id="filter-active"
                label={strings.clients.filterActive}
                checked={hasActive}
                onChange={(e) => {
                  setHasActive(e.target.checked);
                  resetOffset();
                }}
              />
              <Checkbox
                id="filter-banned"
                label={strings.clients.filterBanned}
                checked={bannedOnly}
                onChange={(e) => {
                  setBannedOnly(e.target.checked);
                  resetOffset();
                }}
              />
            </div>
          }
        />
      </Panel>

      <ClientDossier clientId={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}
