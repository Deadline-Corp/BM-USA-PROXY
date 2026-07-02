import { useMemo, useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Button } from "@/shared/components/Button";
import { Select } from "@/shared/components/form/Select";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { Num } from "@/shared/components/Num";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { IconRefresh } from "@/shared/components/icons";
import { useConnections, usePoolSummary, useSyncPool } from "@/shared/hooks/usePool";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Connection } from "@/shared/api/types";
import { DeviceCard } from "@/screens/pools/DeviceCard";
import { EditConnectionModal } from "@/screens/pools/EditConnectionModal";

export function PoolsScreen() {
  const toast = useToast();
  const [city, setCity] = useState("");
  const [carrier, setCarrier] = useState("");
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [sellableOnly, setSellableOnly] = useState(false);
  const [editing, setEditing] = useState<Connection | null>(null);
  const { limit, offset, setOffset, resetOffset } = usePagination(60);

  const summaryQuery = usePoolSummary();
  const syncMutation = useSyncPool();

  const params = useMemo(
    () => ({
      city: city || undefined,
      carrier: carrier || undefined,
      online: onlineOnly || undefined,
      sellable: sellableOnly || undefined,
      limit,
      offset,
    }),
    [city, carrier, onlineOnly, sellableOnly, limit, offset],
  );

  const connectionsQuery = useConnections(params);
  const summary = summaryQuery.data;
  const usedPct = summary && summary.slots_total > 0 ? Math.round((summary.slots_used / summary.slots_total) * 100) : 0;

  const cityOptions = useMemo(() => Array.from(new Set((summary?.cities ?? []).map((c) => c.city))), [summary]);
  const carrierOptions = useMemo(() => Array.from(new Set((summary?.cities ?? []).map((c) => c.carrier))), [summary]);

  async function handleSync() {
    try {
      await syncMutation.mutateAsync();
      toast.success(strings.pools.syncDone);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead
        title={strings.pools.title}
        subtitle={strings.pools.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={handleSync} isLoading={syncMutation.isPending}>
            <IconRefresh />
            {syncMutation.isPending ? strings.pools.syncing : strings.pools.sync}
          </Button>
        }
      />

      {/* Summary bar */}
      {summaryQuery.isLoading ? (
        <Skeleton className="h-[90px] rounded-lg mb-5" />
      ) : summaryQuery.isError ? (
        <div className="mb-5">
          <ErrorState onRetry={() => summaryQuery.refetch()} />
        </div>
      ) : (
        <div className="flex items-stretch bg-surface border border-border rounded-lg mb-5 overflow-hidden flex-wrap">
          <SummaryCell label={strings.pools.slots} value={summary?.slots_total ?? 0} />
          <SummaryCell label={strings.pools.used} value={summary?.slots_used ?? 0} tone="accent" />
          <SummaryCell label={strings.pools.free} value={summary?.slots_free ?? 0} tone="success" />
          <div className="flex-1 min-w-[220px] px-6 py-3.5 border-l border-border flex flex-col gap-1.5 justify-center">
            <div className="flex justify-between items-baseline">
              <span className="text-[.69rem] uppercase tracking-[.08em] text-text-3">Capacity</span>
              <span className="font-mono tabular-nums text-[.78rem] text-text-2">{usedPct}%</span>
            </div>
            <div className="h-[5px] bg-surface-2 rounded-full overflow-hidden">
              <div className="h-full bg-accent rounded-full transition-[width] duration-300 ease-brand" style={{ width: `${usedPct}%` }} />
            </div>
            <div className="flex gap-3.5 text-[.7rem] text-text-3">
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-success" />Online</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-warning" />Full</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-text-3" />Offline</span>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap mb-4">
        <Select
          value={city}
          onChange={(e) => {
            setCity(e.target.value);
            resetOffset();
          }}
          className="min-w-[160px]"
        >
          <option value="">{strings.pools.filterCity}: {strings.common.all}</option>
          {cityOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Select
          value={carrier}
          onChange={(e) => {
            setCarrier(e.target.value);
            resetOffset();
          }}
          className="min-w-[160px]"
        >
          <option value="">{strings.pools.filterCarrier}: {strings.common.all}</option>
          {carrierOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Checkbox
          id="pools-online"
          label={strings.pools.filterOnline}
          checked={onlineOnly}
          onChange={(e) => {
            setOnlineOnly(e.target.checked);
            resetOffset();
          }}
        />
        <Checkbox
          id="pools-sellable"
          label={strings.pools.filterSellable}
          checked={sellableOnly}
          onChange={(e) => {
            setSellableOnly(e.target.checked);
            resetOffset();
          }}
        />
      </div>

      {/* Device grid */}
      {connectionsQuery.isLoading ? (
        <div className="grid gap-[13px]" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(268px, 1fr))" }}>
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[190px] rounded-lg" />
          ))}
        </div>
      ) : connectionsQuery.isError ? (
        <ErrorState onRetry={() => connectionsQuery.refetch()} />
      ) : (connectionsQuery.data?.items.length ?? 0) === 0 ? (
        <EmptyState title="No connections found" hint="Try syncing the pool or adjusting filters." />
      ) : (
        <div className="grid gap-[13px]" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(268px, 1fr))" }}>
          {connectionsQuery.data?.items.map((c) => (
            <DeviceCard key={c.id} connection={c} onEdit={setEditing} />
          ))}
        </div>
      )}

      {connectionsQuery.data && connectionsQuery.data.total > limit && (
        <div className="flex items-center justify-center gap-3 mt-5">
          <Button variant="ghost" size="sm" onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}>
            Previous
          </Button>
          <span className="text-[.8rem] text-text-3 font-mono tabular-nums">
            <Num value={offset + 1} />–<Num value={Math.min(offset + limit, connectionsQuery.data.total)} /> of <Num value={connectionsQuery.data.total} />
          </span>
          <Button variant="ghost" size="sm" onClick={() => setOffset(offset + limit)} disabled={offset + limit >= connectionsQuery.data.total}>
            Next
          </Button>
        </div>
      )}

      <EditConnectionModal connection={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

function SummaryCell({ label, value, tone }: { label: string; value: number; tone?: "accent" | "success" }) {
  const toneClass = tone === "accent" ? "text-accent" : tone === "success" ? "text-success" : "text-text";
  return (
    <div className="flex flex-col gap-0.5 px-6 py-3.5 min-w-[90px] border-l border-border first:border-l-0">
      <span className="text-[.69rem] uppercase tracking-[.08em] text-text-3">{label}</span>
      <span className={`font-mono tabular-nums text-[1.55rem] font-semibold leading-none tracking-[-0.02em] ${toneClass}`}>
        <Num value={value} />
      </span>
    </div>
  );
}
