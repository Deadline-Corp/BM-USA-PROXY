import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { Select } from "@/shared/components/form/Select";
import { formatDateTime } from "@/shared/lib/format";
import { useDepositLedger, useLedgerSummary } from "@/shared/hooks/useLedger";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { DepositLedgerEntry } from "@/shared/api/types";

const STATUSES = [
  "detected", "confirming", "confirmed", "matched", "paid", "underpaid",
  "overpaid", "unmatched", "expired_deposit", "orphaned", "reorg_rollback",
];
const CHAINS = ["tron", "ethereum", "bsc", "solana", "bitcoin", "litecoin"];

export function LedgerScreen() {
  const { limit, offset, setOffset } = usePagination();
  const [status, setStatus] = useState("");
  const [chain, setChain] = useState("");

  const params = useMemo(
    () => ({ limit, offset, ...(status ? { status } : {}), ...(chain ? { chain } : {}) }),
    [limit, offset, status, chain],
  );
  const query = useDepositLedger(params);
  const summary = useLedgerSummary();

  const columns = useMemo<ColumnDef<DepositLedgerEntry, any>[]>(
    () => [
      {
        header: strings.ledger.colTime,
        accessorKey: "created_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem]">{formatDateTime(row.original.created_at)}</span>
        ),
      },
      {
        header: strings.ledger.colChain,
        accessorKey: "chain",
        cell: ({ row }) => (
          <span className="text-[.82rem]">
            <span className="capitalize text-text">{row.original.chain}</span>
            <span className="text-text-3"> · {row.original.asset} {row.original.network}</span>
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
            <div className="font-mono text-[.82rem] text-text">
              {row.original.amount} {row.original.asset}
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
        cell: ({ row }) => (
          <span className="font-mono text-[.76rem] text-text-2" title={row.original.txid}>
            {row.original.txid.slice(0, 10)}…
          </span>
        ),
      },
      {
        header: strings.ledger.colConfs,
        accessorKey: "confirmations",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-[.8rem]">{row.original.confirmations}</span>
        ),
      },
      {
        header: strings.ledger.colUser,
        accessorKey: "user",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{row.original.user ?? "—"}</span>,
      },
      {
        header: strings.ledger.colInvoice,
        accessorKey: "invoice_id",
        cell: ({ row }) => (
          <span className="font-mono text-[.76rem] text-text-2">
            {row.original.invoice_id ? `#${row.original.invoice_id}` : "—"}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div>
      <PageHead title={strings.ledger.title} subtitle={strings.ledger.subtitle} />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <SummaryChip label={strings.ledger.events24h} value={summary.data?.events_24h ?? 0} />
        <SummaryChip
          label={strings.ledger.unmatched}
          value={summary.data?.unmatched_total ?? 0}
          tone={summary.data && summary.data.unmatched_total > 0 ? "warning" : "neutral"}
        />
        <div className="flex-1" />
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">{strings.ledger.filterAllStatuses}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
        <Select
          value={chain}
          onChange={(e) => {
            setChain(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">{strings.ledger.filterAllChains}</option>
          {CHAINS.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </Select>
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
          emptyTitle={strings.ledger.empty}
        />
      </Panel>
    </div>
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
