import { useEffect, useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import clsx from "clsx";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge, formatStatusLabel } from "@/shared/components/StatusBadge";
import { DateFilterPill, FilterPill } from "@/shared/components/FilterPill";
import { FilterBar } from "@/shared/components/TableFilters";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { useTariffs } from "@/shared/hooks/useTariffs";
import { Num } from "@/shared/components/Num";
import { formatDateTime } from "@/shared/lib/format";
import { useManualReviewOrders, useOrdersList } from "@/shared/hooks/useOrders";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import { OrderNumber } from "@/shared/components/OrderNumber";
import type { Order } from "@/shared/api/types";
import { OrderDetail } from "@/screens/orders/OrderDetail";

type Tab = "all" | "manual_review";

/** Order states an operator actually goes looking for. */
const STATUSES = [
  "awaiting_payment", "paid", "provisioning", "completed",
  "manual_review", "expired", "cancelled", "refunded",
];

export function OrdersScreen() {
  const [tab, setTab] = useState<Tab>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { limit, offset, setOffset } = usePagination();

  // This screen had no search and no filters at all, so finding the order a customer is
  // asking about meant paging through everything. Same controls as the payments screen —
  // moving between the two should not mean learning a second set.
  const [status, setStatus] = useState("");
  const [tariff, setTariff] = useState("");
  const [since, setSince] = useState("");
  const [before, setBefore] = useState("");
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const q = useDebouncedValue(search.trim());

  const plans = useTariffs();
  const filtered = Boolean(status || tariff || since || before || q);
  const clearAll = () => {
    setStatus("");
    setTariff("");
    setSince("");
    setBefore("");
    setSearch("");
  };

  // Any narrowing goes back to page 1: staying on page 7 of the old result set lands on an
  // empty page, which reads as "there is nothing" rather than "you moved".
  useEffect(() => {
    setOffset(0);
  }, [status, tariff, since, before, q, sorting, setOffset]);

  const allParams = useMemo(
    () => ({
      limit,
      offset,
      sort: sorting[0]?.id ?? "created_at",
      order: sorting[0]?.desc === false ? "asc" : "desc",
      ...(status ? { status } : {}),
      ...(tariff ? { tariff } : {}),
      ...(since ? { since } : {}),
      ...(before ? { before } : {}),
      ...(q ? { q } : {}),
    }),
    [limit, offset, status, tariff, since, before, q, sorting],
  );
  const allQuery = useOrdersList(allParams);
  const manualQuery = useManualReviewOrders();

  const isManual = tab === "manual_review";
  const activeData = isManual ? manualQuery.data : allQuery.data;
  const isLoading = isManual ? manualQuery.isLoading : allQuery.isLoading;
  const isError = isManual ? manualQuery.isError : allQuery.isError;
  const refetch = isManual ? manualQuery.refetch : allQuery.refetch;

  const columns = useMemo<ColumnDef<Order, any>[]>(
    () => [
      {
        header: strings.orders.colOrder,
        accessorKey: "number",
        cell: ({ row }) => <OrderNumber value={row.original.number} />,
      },
      {
        header: strings.orders.colUser,
        accessorKey: "user",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{row.original.user}</span>,
      },
      {
        header: strings.orders.colProvider,
        accessorKey: "provider",
      },
      {
        header: strings.orders.colPlan,
        accessorKey: "tariff_code",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-[.82rem] whitespace-nowrap">
            <span className="text-text">{row.original.tariff_code}</span>
            {row.original.quantity > 1 ? (
              <span className="text-text-3">{` × ${row.original.quantity}`}</span>
            ) : null}
          </span>
        ),
      },
      {
        header: strings.orders.colAmount,
        accessorKey: "amount_usd",
        cell: ({ row }) => <Num value={row.original.amount_usd} usd className="text-text" />,
      },
      {
        header: strings.orders.colStatus,
        accessorKey: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        header: "Created",
        accessorKey: "created_at",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDateTime(row.original.created_at)}</span>,
      },
    ],
    [],
  );

  return (
    <div>
      <PageHead title={strings.orders.title} subtitle={strings.orders.subtitle} />

      <div className="flex items-center gap-1 mb-4 bg-surface-2 border border-border rounded-lg p-1 w-fit">
        <TabButton active={tab === "all"} onClick={() => setTab("all")}>
          {strings.orders.tabAll}
        </TabButton>
        <TabButton active={tab === "manual_review"} onClick={() => setTab("manual_review")}>
          {strings.orders.tabManualReview}
          {manualQuery.data && manualQuery.data.total > 0 && (
            <span className="ml-1.5 font-mono tabular-nums text-[.68rem] bg-warning-soft text-warning px-1.5 py-0.5 rounded-full">
              {manualQuery.data.total}
            </span>
          )}
        </TabButton>
      </div>

      <Panel>
        <DataTable
          columns={columns}
          data={activeData?.items ?? []}
          total={activeData?.total ?? 0}
          limit={limit}
          offset={offset}
          onOffsetChange={setOffset}
          isLoading={isLoading}
          isError={isError}
          onRetry={refetch}
          onRowClick={(row) => setSelectedId(row.id)}
          getRowId={(row) => row.id}
          sorting={isManual ? undefined : sorting}
          onSortingChange={isManual ? undefined : setSorting}
          emptyTitle={
            isManual
              ? strings.orders.emptyManualReview
              : filtered
                ? strings.orders.emptyFiltered
                : strings.orders.empty
          }
          emptyHint={!isManual && filtered ? strings.orders.emptyFilteredHint : undefined}
          toolbar={
            // The manual-review tab is a short, complete worklist — filtering a queue you
            // are meant to empty only hides what is left in it.
            isManual ? undefined : (
              <FilterBar
                search={search}
                onSearchChange={setSearch}
                searchPlaceholder={strings.orders.searchPlaceholder}
                isFiltered={filtered}
                onClear={clearAll}
              >
                <FilterPill
                  label={strings.orders.filterStatus}
                  value={status}
                  onChange={setStatus}
                  options={STATUSES.map((s) => ({ value: s, label: formatStatusLabel(s) }))}
                  allLabel={strings.common.all}
                />
                <FilterPill
                  label={strings.orders.filterPlan}
                  value={tariff}
                  onChange={setTariff}
                  options={(plans.data ?? []).map((p) => ({ value: p.code, label: p.name }))}
                  allLabel={strings.common.all}
                />
                <DateFilterPill
                  label={strings.orders.filterFrom}
                  value={since}
                  onChange={setSince}
                  anyLabel={strings.orders.filterAnyDate}
                />
                <DateFilterPill
                  label={strings.orders.filterTo}
                  value={before}
                  onChange={setBefore}
                  anyLabel={strings.orders.filterAnyDate}
                />
              </FilterBar>
            )
          }
        />
      </Panel>

      <OrderDetail orderId={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "px-3.5 py-1.5 rounded-md text-[.82rem] font-semibold transition-colors duration-150 ease-brand flex items-center",
        active ? "bg-surface text-text shadow-sm" : "text-text-2 hover:text-text",
      )}
    >
      {children}
    </button>
  );
}
