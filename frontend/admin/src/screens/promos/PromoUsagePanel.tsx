import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { FilterPill } from "@/shared/components/FilterPill";
import { Num } from "@/shared/components/Num";
import { OrderNumber } from "@/shared/components/OrderNumber";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { usePromoUsage } from "@/shared/hooks/usePromos";
import { usePagination } from "@/shared/hooks/usePagination";
import { formatDateTime } from "@/shared/lib/format";
import { strings } from "@/shared/strings";
import type { PromoCode, PromoUsage } from "@/shared/api/types";

interface PromoUsagePanelProps {
  /** The live codes, for the filter. Deleted ones still appear in the rows themselves —
   *  "All codes" is the only view that can show a retired campaign's sales. */
  codes: PromoCode[];
}

export function PromoUsagePanel({ codes }: PromoUsagePanelProps) {
  const { limit, offset, setOffset, resetOffset } = usePagination(20);
  const [code, setCode] = useState("");

  const { data, isLoading, isError, refetch } = usePromoUsage({
    limit,
    offset,
    code: code || undefined,
  });

  const columns = useMemo<ColumnDef<PromoUsage, any>[]>(
    () => [
      {
        header: strings.promos.colWhen,
        accessorKey: "created_at",
        cell: ({ row }) => (
          <span className="font-mono text-[.8rem] whitespace-nowrap">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        header: strings.promos.colClient,
        accessorKey: "client",
        cell: ({ row }) => <span className="text-text">{row.original.client}</span>,
      },
      {
        header: strings.promos.colOrder,
        accessorKey: "order_number",
        cell: ({ row }) => <OrderNumber value={row.original.order_number} />,
      },
      {
        header: strings.promos.code,
        accessorKey: "code",
        cell: ({ row }) => (
          <span className="whitespace-nowrap">
            <span className="font-mono text-[.82rem] text-text">{row.original.code}</span>
            {row.original.percent_off !== null ? (
              <span className="ml-1.5 text-text-3">−{row.original.percent_off}%</span>
            ) : null}
            {/* The campaign is gone but the sale stands. Without the word, an operator
                looking for the code in the list above and not finding it reads the row as
                a mistake. */}
            {row.original.code_deleted ? (
              <span className="ml-1.5 text-[.72rem] uppercase tracking-[.06em] text-text-3">
                {strings.promos.codeRetired}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        header: strings.promos.colPlan,
        accessorKey: "plan",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-text">
            {row.original.plan}
            {/* An extension and a first purchase of the same plan are different sales, and
                the plan name alone cannot tell them apart. */}
            {row.original.is_extension ? (
              <span className="ml-1.5 text-[.72rem] uppercase tracking-[.06em] text-text-3">
                {strings.promos.extension}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        header: strings.promos.colQty,
        accessorKey: "quantity",
        cell: ({ row }) => <Num value={row.original.quantity} className="text-text-2" />,
      },
      {
        header: strings.promos.colDiscount,
        accessorKey: "discount_usd",
        cell: ({ row }) => (
          <Num value={row.original.discount_usd} usd className="text-success" />
        ),
      },
      {
        header: strings.promos.colPaid,
        accessorKey: "amount_usd",
        cell: ({ row }) => <Num value={row.original.amount_usd} usd className="text-text" />,
      },
      {
        header: strings.promos.colStatus,
        accessorKey: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
    ],
    [],
  );

  return (
    <Panel className="mt-5">
      <Panel.Head title={strings.promos.usageTitle} subtitle={strings.promos.usageHint} />
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
        emptyTitle={strings.promos.usageEmpty}
        emptyHint={strings.promos.usageHint}
        toolbar={
          // The pill on its own, without the usual FilterBar: there is nothing here to
          // search for by hand that picking the code does not already answer.
          <div className="flex flex-wrap items-center gap-2">
            <FilterPill
              label={strings.promos.code}
              value={code}
              allLabel={strings.promos.usageAll}
              onChange={(v) => {
                setCode(v);
                // Page 3 of one code is not page 3 of another; staying there shows an
                // empty table and reads as "no uses".
                resetOffset();
              }}
              options={codes.map((c) => ({ value: c.code, label: c.code }))}
            />
          </div>
        }
      />
    </Panel>
  );
}
