import { useEffect, useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge, formatStatusLabel } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { CopyInline } from "@/shared/components/CopyInline";
import { OrderNumber } from "@/shared/components/OrderNumber";
import { DateFilterPill, FilterPill } from "@/shared/components/FilterPill";
import { FilterBar } from "@/shared/components/TableFilters";
import { formatChain, formatCryptoAmount, formatDateTime, formatNetwork } from "@/shared/lib/format";
import { useDepositLedger, useLedgerSummary } from "@/shared/hooks/useLedger";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { ResolveDepositModal } from "@/screens/payments/ResolveDepositModal";
import { InvoicesPanel } from "@/screens/payments/InvoicesPanel";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { DepositLedgerEntry } from "@/shared/api/types";

/**
 * Only states a deposit can actually be found in.
 *
 * Two used to be here and could never match anything, which is worse than a missing
 * option: the operator picks one, gets an empty table, and cannot tell "no such deposits"
 * from "this filter is broken".
 *  - `confirmed` is written by no code path at all — it was only ever in this list.
 *  - `detected` is written once per deposit, but the same tick immediately appends
 *    `confirming` / `unmatched` / a final state, so it is never a deposit's current state.
 *    In full-history view it matches every deposit exactly once, which narrows nothing.
 * Both still exist in the journal; they just are not something to filter by.
 */
const STATUSES = [
  "confirming", "matched", "paid", "underpaid",
  "overpaid", "unmatched", "expired_deposit", "orphaned", "reorg_rollback",
];
const CHAINS = ["tron", "ethereum", "bsc", "solana", "bitcoin", "litecoin"];
const ASSETS = ["USDT", "USDC", "TRX", "ETH", "BNB", "SOL", "BTC", "LTC"];

/** Deposit states that are waiting for a human decision. */
const RESOLVABLE = ["unmatched", "underpaid", "expired_deposit", "orphaned"];

// No minimum length: short queries are the useful ones now. The server matches a coin or
// a chain name by equality ("BTC", "tron") and only falls back to a substring scan over
// hashes and addresses, which is what the old 4-character floor was protecting.

export function LedgerScreen() {
  const [tab, setTab] = useState<"deposits" | "invoices">("deposits");
  const { limit, offset, setOffset } = usePagination();
  const [status, setStatus] = useState("");
  const [chain, setChain] = useState("");
  const [asset, setAsset] = useState("");
  const [since, setSince] = useState("");
  const [before, setBefore] = useState("");
  const [search, setSearch] = useState("");
  const [resolving, setResolving] = useState<DepositLedgerEntry | null>(null);
  // Default to each deposit's current state. The full journal is still one click away, but
  // filtering "Unmatched" over every historical row shows deposits that were resolved long
  // ago — the operator reads that as "still broken".
  const [currentOnly, setCurrentOnly] = useState(true);
  // Newest first by default: the question this screen answers most often is "what just
  // came in". Every other order is one click on a header away.
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);

  const q = useDebouncedValue(search.trim());

  // Any narrowing sends you back to page 1. Staying on page 7 of the old result set lands
  // on an empty page, which reads as "there is nothing" rather than "you moved".
  useEffect(() => {
    setOffset(0);
  }, [status, chain, asset, since, before, q, currentOnly, sorting, setOffset]);

  const params = useMemo(
    () => ({
      limit,
      offset,
      current_only: currentOnly,
      sort: sorting[0]?.id ?? "created_at",
      order: sorting[0]?.desc === false ? "asc" : "desc",
      ...(status ? { status } : {}),
      ...(chain ? { chain } : {}),
      ...(asset ? { asset } : {}),
      ...(since ? { since } : {}),
      ...(before ? { before } : {}),
      ...(q ? { q } : {}),
    }),
    [limit, offset, status, chain, asset, since, before, q, currentOnly, sorting],
  );
  const query = useDepositLedger(params);
  const summary = useLedgerSummary();

  const filtered = Boolean(status || chain || asset || since || before || q);
  const clearAll = () => {
    setStatus("");
    setChain("");
    setAsset("");
    setSince("");
    setBefore("");
    setSearch("");
  };

  const columns = useMemo<ColumnDef<DepositLedgerEntry, any>[]>(
    () => [
      {
        header: strings.ledger.colTime,
        accessorKey: "created_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem] whitespace-nowrap">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        header: strings.ledger.colChain,
        accessorKey: "chain",
        cell: ({ row }) => (
          <span className="text-[.82rem] whitespace-nowrap">
            <span className="text-text">{formatChain(row.original.chain)}</span>
            <span className="text-text-3">
              {" · "}{row.original.asset} {formatNetwork(row.original.network)}
            </span>
          </span>
        ),
      },
      {
        header: strings.ledger.colStatus,
        accessorKey: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        header: strings.ledger.colAmount,
        accessorKey: "amount",
        cell: ({ row }) => (
          <div className="leading-tight">
            <div
              className="font-mono text-[.82rem] text-text whitespace-nowrap"
              title={`${row.original.amount} ${row.original.asset}`}
            >
              {formatCryptoAmount(row.original.amount)} {row.original.asset}
            </div>
            {row.original.amount_usd != null && (
              <Num value={row.original.amount_usd} usd className="text-[.72rem] text-text-3" />
            )}
          </div>
        ),
      },
      {
        header: strings.ledger.colTx,
        accessorKey: "txid",
        enableSorting: false,
        cell: ({ row }) => <CopyInline value={row.original.txid} head={10} />,
      },
      {
        // Who paid. On an unmatched deposit this is the only thread back to the buyer —
        // the operator pastes it into the explorer, or asks the customer to confirm it.
        header: strings.ledger.colFrom,
        accessorKey: "from_address",
        enableSorting: false,
        cell: ({ row }) => <CopyInline value={row.original.from_address} />,
      },
      {
        // Which of our receiving addresses took it — the one thing that says a deposit
        // landed on the rail it was quoted for.
        header: strings.ledger.colTo,
        accessorKey: "to_address",
        enableSorting: false,
        cell: ({ row }) => <CopyInline value={row.original.to_address} />,
      },
      {
        header: strings.ledger.colUser,
        accessorKey: "user",
        enableSorting: false,
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{row.original.user ?? "—"}</span>,
      },
      {
        // The order, not the invoice. The invoice's primary key is internal: nothing in
        // this console or in the buyer's app can be looked up by it, so as a column it
        // was a reference to nowhere. The order id is what the customer quotes.
        header: strings.ledger.colOrder,
        accessorKey: "order_number",
        enableSorting: false,
        cell: ({ row }) => <OrderNumber value={row.original.order_number} />,
      },
      {
        // Without this column the ledger reported stuck money and offered nothing to do
        // about it — the operator could see the problem and not act on it.
        header: strings.ledger.colAction,
        id: "resolve",
        enableSorting: false,
        cell: ({ row }) => {
          // `is_current` matters as much as the status: an old "unmatched" row keeps that
          // word forever, and offering Resolve on it after the deposit was settled only
          // produces a 409 the operator cannot act on.
          if (!row.original.is_current || !RESOLVABLE.includes(row.original.status)) return null;
          // A written-off deposit is already decided. Reopening it stays possible — a
          // write-off can be a mistake — but it is not outstanding work, so it must not
          // wear the same "needs attention" styling as a genuinely stuck payment.
          const decided = row.original.status === "orphaned";
          return (
            <button
              type="button"
              className={
                "rounded border px-2 py-1 text-[.75rem] font-medium transition-colors whitespace-nowrap " +
                (decided
                  ? "border-border text-text-3 hover:bg-surface-2"
                  : "border-warning/50 text-warning hover:bg-warning/10")
              }
              onClick={() => setResolving(row.original)}
            >
              {decided ? strings.ledger.reopen : strings.ledger.resolve}
            </button>
          );
        },
      },
    ],
    [],
  );

  return (
    <div>
      <PageHead title={strings.ledger.title} subtitle={strings.ledger.subtitle} />

      {/* Two halves of the same subject, kept on one screen: what arrived, and what is
          owed. Splitting them across the menu would leave the operator answering "did this
          customer pay?" in one place and "what is he supposed to pay?" in another. */}
      <div className="flex items-center gap-1 mb-4 bg-surface-2 border border-border rounded-lg p-1 w-fit">
        <TabButton active={tab === "deposits"} onClick={() => setTab("deposits")}>
          {strings.ledger.tabDeposits}
        </TabButton>
        <TabButton active={tab === "invoices"} onClick={() => setTab("invoices")}>
          {strings.ledger.tabInvoices}
        </TabButton>
      </div>

      {tab === "invoices" ? (
        <InvoicesPanel />
      ) : (
      <>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <SummaryChip label={strings.ledger.events24h} value={summary.data?.events_24h ?? 0} />
        <SummaryChip
          label={strings.ledger.unmatched}
          value={summary.data?.unmatched_total ?? 0}
          tone={summary.data && summary.data.unmatched_total > 0 ? "warning" : "neutral"}
        />
      </div>

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
          emptyTitle={filtered ? strings.ledger.emptyFiltered : strings.ledger.empty}
          emptyHint={filtered ? strings.ledger.emptyFilteredHint : undefined}
          toolbar={
            // This screen's toolbar is where the shape came from; it now renders through
            // the shared component so the other five cannot drift away from it.
            <FilterBar
              search={search}
              onSearchChange={setSearch}
              searchPlaceholder={strings.ledger.searchPlaceholder}
              isFiltered={filtered}
              onClear={clearAll}
            >
              <FilterPill
                  label={strings.ledger.filterView}
                  value={currentOnly ? "" : "all"}
                  onChange={(v) => setCurrentOnly(v !== "all")}
                  options={[{ value: "all", label: strings.ledger.viewHistory }]}
                  allLabel={strings.ledger.viewCurrent}
                />
                <FilterPill
                  label={strings.ledger.filterStatus}
                  value={status}
                  onChange={setStatus}
                  options={STATUSES.map((s) => ({ value: s, label: formatStatusLabel(s) }))}
                  allLabel={strings.common.all}
                />
                <FilterPill
                  label={strings.ledger.filterChain}
                  value={chain}
                  onChange={setChain}
                  options={CHAINS.map((c) => ({ value: c, label: formatChain(c) }))}
                  allLabel={strings.common.all}
                />
                <FilterPill
                  label={strings.ledger.filterAsset}
                  value={asset}
                  onChange={setAsset}
                  options={ASSETS.map((a) => ({ value: a, label: a }))}
                  allLabel={strings.common.all}
                />
                <DateFilterPill
                  label={strings.ledger.filterFrom}
                  value={since}
                  onChange={setSince}
                  anyLabel={strings.ledger.filterAnyDate}
                />
              <DateFilterPill
                label={strings.ledger.filterTo}
                value={before}
                onChange={setBefore}
                anyLabel={strings.ledger.filterAnyDate}
              />
            </FilterBar>
          }
        />
      </Panel>

      <ResolveDepositModal deposit={resolving} onClose={() => setResolving(null)} />
      </>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "px-3.5 py-1.5 rounded-md text-[.82rem] font-semibold transition-colors duration-150 ease-brand flex items-center " +
        (active ? "bg-surface text-text shadow-sm" : "text-text-2 hover:text-text")
      }
    >
      {children}
    </button>
  );
}

function SummaryChip({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "warning";
}) {
  return (
    <div className="flex items-baseline gap-2 bg-surface-2 border border-border rounded-lg px-3.5 py-2">
      <span
        className={
          "font-mono tabular-nums text-[1.05rem] font-semibold " +
          (tone === "warning" && value > 0 ? "text-warning" : "text-text")
        }
      >
        {value}
      </span>
      <span className="text-[.76rem] text-text-3">{label}</span>
    </div>
  );
}
