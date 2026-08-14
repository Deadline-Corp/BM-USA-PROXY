import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Button } from "@/shared/components/Button";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { FilterBar } from "@/shared/components/TableFilters";
import { DateFilterPill, FilterPill } from "@/shared/components/FilterPill";
import { initials, formatDate } from "@/shared/lib/format";
import { useClientsList } from "@/shared/hooks/useClients";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { Client } from "@/shared/api/types";
import { ClientDossier } from "@/screens/clients/ClientDossier";
import { IconCheckPlain, IconRefresh } from "@/shared/components/icons";

export function ClientsScreen() {
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  // Three-state pills rather than checkboxes: a checkbox can only say "only the banned
  // ones", never "only the ones who are not", and the second question gets asked too.
  const [access, setAccess] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [before, setBefore] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { limit, offset, setOffset } = usePagination();
  const query = useDebouncedValue(search.trim());

  useEffect(() => {
    setOffset(0);
  }, [query, access, status, since, before, setOffset]);

  const params = useMemo(
    () => ({
      limit,
      offset,
      ...(query ? { q: query } : {}),
      ...(access ? { has_active: access === "yes" } : {}),
      ...(status ? { banned: status === "banned" } : {}),
      ...(since ? { since } : {}),
      ...(before ? { before } : {}),
    }),
    [query, access, status, since, before, limit, offset],
  );

  const isFiltered = Boolean(query || access || status || since || before);
  const clearAll = () => {
    setSearch("");
    setAccess("");
    setStatus("");
    setSince("");
    setBefore("");
  };

  const { data, isLoading, isError, refetch, isFetching } = useClientsList(params);

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
                <div className="flex items-center gap-1.5">
                  <span className="text-text font-medium truncate min-w-0">{c.display_name ?? "Unnamed"}</span>
                  {c.unread_messages > 0 && (
                    <span
                      className="inline-flex items-center justify-center flex-none min-w-[17px] h-[17px] px-1 rounded-full bg-accent font-mono text-[.66rem] font-semibold tabular-nums text-on-accent"
                      title={`${c.unread_messages} unread message${c.unread_messages === 1 ? "" : "s"}`}
                    >
                      {c.unread_messages}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  {/* Handle AND telegram id, not one or the other. A handle can be changed
                      at any moment — the same person then looks like a stranger in every
                      screenshot and search anyone made before. The id never changes, and
                      it is what this client's whole history is keyed on. */}
                  <span className="font-mono text-[.78rem] text-text-3 truncate min-w-0">
                    {c.telegram_username ? `@${c.telegram_username} · ${c.telegram_id}` : c.telegram_id}
                  </span>
                  {c.terms_accepted && (
                    <span className="flex-none" title={strings.clients.termsAccepted}>
                      <IconCheckPlain className="w-3 h-3 text-success" />
                    </span>
                  )}
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
      <PageHead
        title={strings.clients.title}
        subtitle={strings.clients.subtitle}
        actions={
          <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <IconRefresh className={isFetching ? "animate-spin" : undefined} />
            {strings.common.refresh}
          </Button>
        }
      />

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
            <FilterBar
              search={search}
              onSearchChange={setSearch}
              searchPlaceholder={strings.clients.searchPlaceholder}
              isFiltered={isFiltered}
              onClear={clearAll}
            >
              <FilterPill
                label={strings.clients.colAccess}
                value={access}
                onChange={setAccess}
                options={[
                  { value: "yes", label: "Has access" },
                  { value: "no", label: "No access" },
                ]}
                allLabel={strings.common.all}
              />
              <FilterPill
                label={strings.clients.colStatus}
                value={status}
                onChange={setStatus}
                options={[
                  { value: "active", label: strings.common.active },
                  { value: "banned", label: strings.clients.banned },
                ]}
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

      <ClientDossier clientId={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}
