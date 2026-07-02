import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import clsx from "clsx";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { formatDateTime } from "@/shared/lib/format";
import { useManualReviewOrders, useOrdersList } from "@/shared/hooks/useOrders";
import { usePagination } from "@/shared/hooks/usePagination";
import { strings } from "@/shared/strings";
import type { Order } from "@/shared/api/types";
import { OrderDetail } from "@/screens/orders/OrderDetail";

type Tab = "all" | "manual_review";

export function OrdersScreen() {
  const [tab, setTab] = useState<Tab>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { limit, offset, setOffset } = usePagination();

  const allParams = useMemo(() => ({ limit, offset }), [limit, offset]);
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
        accessorKey: "id",
        cell: ({ row }) => <span className="font-mono text-[.8rem] text-text">{row.original.id.slice(0, 10)}</span>,
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
          emptyTitle={isManual ? "Nothing needs manual review" : "No orders yet"}
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
