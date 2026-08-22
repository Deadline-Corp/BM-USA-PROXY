import { useEffect, useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge, formatStatusLabel } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { CopyInline } from "@/shared/components/CopyInline";
import { OrderNumber } from "@/shared/components/OrderNumber";
import { DateFilterPill, FilterPill } from "@/shared/components/FilterPill";
import { FilterBar } from "@/shared/components/TableFilters";
import { formatChain, formatCryptoAmount, formatDateTime, formatNetwork } from "@/shared/lib/format";
import { useInvoices } from "@/shared/hooks/useLedger";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import { CHAINS, ASSETS } from "@/shared/constants/payments";
import type { InvoiceRow } from "@/shared/api/types";

/** `awaiting` is first and is not a real column value — it is the three statuses that all
 *  mean "the money has not landed", which is the one question this table exists for. */
const STATUSES = [
  "awaiting", "pending", "confirming", "paid", "expired",
  "underpaid", "overpaid", "manual_review", "failed",
];

/**
 * Invoices raised, paid or not.
 *
 * The ledger beside this shows deposits the watcher observed, so an invoice nobody has
 * paid appears nowhere in it — correctly, since no money moved. That left the operator
 * with no way to see what was outstanding except opening clients one at a time, which is
 * not a list anybody can work from when a customer writes asking about their payment.
 */
export function InvoicesPanel() {
  const { limit, offset, setOffset } = usePagination();
  // Opens on what is owed rather than on everything: the paid ones are already answered
  // by the deposit ledger, and an operator coming here is chasing something unfinished.
  const [status, setStatus] = useState("awaiting");
  const [chain, setChain] = useState("");
  const [asset, setAsset] = useState("");
  const [since, setSince] = useState("");
  const [before, setBefore] = useState("");
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);

  const q = useDebouncedValue(search.trim());

  useEffect(() => {
    setOffset(0);
  }, [status, chain, asset, since, before, q, sorting, setOffset]);

  const params = useMemo(
    () => ({
      limit,
      offset,
      sort: sorting[0]?.id ?? "created_at",
      order: sorting[0]?.desc === false ? "asc" : "desc",
      ...(status ? { status } : {}),
      ...(chain ? { chain } : {}),
      ...(asset ? { asset } : {}),
      ...(since ? { since } : {}),
      ...(before ? { before } : {}),
      ...(q ? { q } : {}),
    }),
    [limit, offset, status, chain, asset, since, before, q, sorting],
  );
  const query = useInvoices(params);

  const filtered = Boolean(status || chain || asset || since || before || q);
  const clearAll = () => {
    setStatus("");
    setChain("");
    setAsset("");
    setSince("");
    setBefore("");
    setSearch("");
  };

  const columns = useMemo<ColumnDef<InvoiceRow, any>[]>(
    () => [
      {
        header: strings.invoices.colCreated,
        accessorKey: "created_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem] whitespace-nowrap">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        header: strings.invoices.colOrder,
        accessorKey: "order_number",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="leading-tight">
            <OrderNumber value={row.original.order_number} />
            <div className="text-[.72rem] text-text-3">
              {row.original.tariff_code}
              {row.original.quantity > 1 ? ` × ${row.original.quantity}` : ""}
            </div>
          </div>
        ),
      },
      {
        header: strings.invoices.colUser,
        accessorKey: "user",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem]">{row.original.user ?? "—"}</span>
        ),
      },
      {
        header: strings.invoices.colStatus,
        accessorKey: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        header: strings.invoices.colAmount,
        accessorKey: "amount_usd",
        cell: ({ row }) => (
          <div className="leading-tight">
            {/* The crypto figure first: it is the number the buyer is looking at and the
                one the watcher matches to the last digit. */}
            <div className="font-mono text-[.82rem] text-text whitespace-nowrap">
              {row.original.crypto_amount !== null
                ? `${formatCryptoAmount(String(row.original.crypto_amount))} ${row.original.crypto_currency ?? ""}`
                : "—"}
            </div>
            <div className="text-[.72rem] text-text-3">
              <Num value={row.original.amount_usd} usd />
            </div>
          </div>
        ),
      },
      {
        header: strings.invoices.colChain,
        accessorKey: "chain",
        cell: ({ row }) => (
          // Invoices raised before the on-chain provider carry no chain of their own, and
          // a bare em-dash in front of the network reads as missing data rather than as
          // "the network says it".
          <span className="text-[.82rem] whitespace-nowrap">
            {row.original.chain ? (
              <span className="text-text">{formatChain(row.original.chain)}</span>
            ) : null}
            {row.original.crypto_network ? (
              <span className={row.original.chain ? "text-text-3" : "text-text"}>
                {row.original.chain ? " · " : ""}
                {formatNetwork(row.original.crypto_network)}
              </span>
            ) : null}
            {!row.original.chain && !row.original.crypto_network ? (
              <span className="text-text-3">—</span>
            ) : null}
          </span>
        ),
      },
      {
        header: strings.invoices.colPayTo,
        accessorKey: "pay_address",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.pay_address ? (
            <CopyInline value={row.original.pay_address} />
          ) : (
            <span className="text-text-3">—</span>
          ),
      },
      {
        header: strings.invoices.colExpires,
        accessorKey: "expires_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem] whitespace-nowrap text-text-2">
            {formatDateTime(row.original.expires_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Panel>
      <DataTable
        columns={columns}
        data={query.data?.items ?? []}
        total={query.data?.total ?? 0}
        limit={limit}
        offset={offset}
        onOffsetChange={setOffset}
        isLoading={query.isLoading}
        isError={query.isError}
        onRetry={query.refetch}
        getRowId={(row) => row.id}
        sorting={sorting}
        onSortingChange={setSorting}
        emptyTitle={filtered ? strings.invoices.emptyFiltered : strings.invoices.empty}
        emptyHint={filtered ? strings.invoices.emptyFilteredHint : undefined}
        toolbar={
          <FilterBar
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.invoices.searchPlaceholder}
            isFiltered={filtered}
            onClear={clearAll}
          >
            <FilterPill
              label={strings.invoices.filterStatus}
              value={status}
              onChange={setStatus}
              options={STATUSES.map((s) => ({
                value: s,
                label: s === "awaiting" ? strings.invoices.statusAwaiting : formatStatusLabel(s),
              }))}
              allLabel={strings.common.all}
            />
            <FilterPill
              label={strings.invoices.filterChain}
              value={chain}
              onChange={setChain}
              options={CHAINS.map((c) => ({ value: c, label: formatChain(c) }))}
              allLabel={strings.common.all}
            />
            <FilterPill
              label={strings.invoices.filterAsset}
              value={asset}
              onChange={setAsset}
              options={ASSETS.map((a) => ({ value: a, label: a }))}
              allLabel={strings.common.all}
            />
            <DateFilterPill
              label={strings.invoices.filterFrom}
              value={since}
              onChange={setSince}
              anyLabel={strings.invoices.filterAnyDate}
            />
            <DateFilterPill
              label={strings.invoices.filterTo}
              value={before}
              onChange={setBefore}
              anyLabel={strings.invoices.filterAnyDate}
            />
          </FilterBar>
        }
      />
    </Panel>
  );
}
