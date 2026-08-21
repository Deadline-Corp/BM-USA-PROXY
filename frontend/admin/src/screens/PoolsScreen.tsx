import { useEffect, useMemo, useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Button } from "@/shared/components/Button";
import { Num } from "@/shared/components/Num";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { FilterBar } from "@/shared/components/TableFilters";
import { FilterPill } from "@/shared/components/FilterPill";
import { IconRefresh } from "@/shared/components/icons";
import { useConnections, usePoolSummary, useSyncPool } from "@/shared/hooks/usePool";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Connection } from "@/shared/api/types";
import { DeviceCard } from "@/screens/pools/DeviceCard";
import { EditConnectionModal } from "@/screens/pools/EditConnectionModal";

export function PoolsScreen() {
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [city, setCity] = useState("");
  const [carrier, setCarrier] = useState("");
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [sellableOnly, setSellableOnly] = useState(false);
  const [editing, setEditing] = useState<Connection | null>(null);
  const { limit, offset, setOffset } = usePagination(60);
  const q = useDebouncedValue(search.trim());

  const summaryQuery = usePoolSummary();
  const syncMutation = useSyncPool();

  useEffect(() => {
    setOffset(0);
  }, [q, city, carrier, onlineOnly, sellableOnly, setOffset]);

  const params = useMemo(
    () => ({
      limit,
      offset,
      ...(q ? { q } : {}),
      ...(city ? { city } : {}),
      ...(carrier ? { carrier } : {}),
      ...(onlineOnly ? { online: true } : {}),
      ...(sellableOnly ? { sellable: true } : {}),
    }),
    [q, city, carrier, onlineOnly, sellableOnly, limit, offset],
  );

  const isFiltered = Boolean(q || city || carrier || onlineOnly || sellableOnly);
  const clearAll = () => {
    setSearch("");
    setCity("");
    setCarrier("");
    setOnlineOnly(false);
    setSellableOnly(false);
  };

  const connectionsQuery = useConnections(params);
  const summary = summaryQuery.data;
  const totalSlots = summary?.slots_total ?? 0;
  const usedSlots = summary?.slots_used ?? 0;
  const freeSlots = summary?.slots_free ?? 0;
  const heldSlots = summary?.slots_held ?? 0;
  const reservedSlots = summary?.slots_reserved ?? 0;
  const unavailableSlots = summary?.slots_unavailable ?? 0;
  const usedPct = totalSlots > 0 ? Math.round((usedSlots / totalSlots) * 100) : 0;
  /** Share of the pool, for a bar segment. Unrounded so the three always fill the track. */
  const pct = (n: number) => (totalSlots > 0 ? (n / totalSlots) * 100 : 0);

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
        <div className="bg-surface border border-border rounded-lg mb-5 overflow-hidden">
        <div className="flex items-stretch flex-wrap">
          {/* Free before Busy, matching the legend to the right. It is also the number an
              operator looks for first — "can we sell right now" comes before "how much is
              out". */}
          <SummaryCell label={strings.pools.slots} value={summary?.slots_total ?? 0} />
          <SummaryCell label={strings.pools.free} value={summary?.slots_free ?? 0} tone="success" />
          <SummaryCell label={strings.pools.used} value={summary?.slots_used ?? 0} tone="accent" />
          {/* The fourth bucket had a colour in the bar and a number in the legend but no
              cell of its own, so the three cells never added up to the total and the gap
              had no name. Unavailable is the one an operator has to act on — it is stock
              that cannot be sold. */}
          {/* Held in iproxy is its own bucket, not a shade of Unavailable: the fix for
              it is different from every other state — somebody opens the iproxy console
              and releases the phone. Until then it earns nothing while looking like stock. */}
          <SummaryCell label={strings.pools.busyByAdmin} value={heldSlots} tone="warning" />
          {/* Also its own bucket, and for the same reason as Held: nothing is wrong with
              these phones, they are simply promised to somebody who has not paid yet. Folded
              into Free they would make this screen answer "can we sell?" with a number the
              allocator will not honour; folded into Unavailable they would look broken. */}
          <SummaryCell label={strings.pools.reservedShort} value={reservedSlots} />
          <SummaryCell label={strings.pools.unavailable} value={unavailableSlots} />
        </div>

        {/* Capacity on its own full-width band under the counts, divided from them by a
            rule rather than a gap — it reads as the same panel, which it is. It used to sit
            beside the counts as a sixth column, and a fifth bucket left that column too
            narrow for the legend: "Held in iproxy" broke across three lines and the five
            entries stopped reading as one list. The bar wants width more than they do. */}
        <div className="px-6 py-3.5 flex flex-col gap-2 border-t border-border">
            <div className="flex justify-between items-baseline">
              <span className="text-[.69rem] uppercase tracking-[.08em] text-text-3">Capacity</span>
              <span className="font-mono tabular-nums text-[.78rem] text-text-2">{usedPct}%</span>
            </div>
            {/* The legend promised three colours; the bar drew one solid accent fill, so
                nothing under it matched anything in it. It is a real stacked bar now, and
                the three segments are the backend's three buckets, which always cover the
                pool. Counts sit in the legend because proportions alone hid the story
                here: a third amber reads as "a third sold" when it in fact means one node
                sold and two unreachable. */}
            <div className="h-[5px] bg-surface-2 rounded-full overflow-hidden flex">
              <div
                className="h-full bg-success transition-[width] duration-300 ease-brand"
                style={{ width: `${pct(freeSlots)}%` }}
              />
              <div
                className="h-full bg-warning transition-[width] duration-300 ease-brand"
                style={{ width: `${pct(usedSlots)}%` }}
              />
              <div
                className="h-full bg-warning/50 transition-[width] duration-300 ease-brand"
                style={{ width: `${pct(heldSlots)}%` }}
              />
              <div
                className="h-full bg-accent/40 transition-[width] duration-300 ease-brand"
                style={{ width: `${pct(reservedSlots)}%` }}
              />
              <div
                className="h-full bg-text-3 transition-[width] duration-300 ease-brand"
                style={{ width: `${pct(unavailableSlots)}%` }}
              />
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-[.7rem] text-text-3">
              {/* Free / Used echo the summary cells to the left, so the same number is not
                  called two different things a few centimetres apart. */}
              <span className="flex items-center gap-1 whitespace-nowrap">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />Free {freeSlots}
              </span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                <span className="w-1.5 h-1.5 rounded-full bg-warning" />Busy {usedSlots}
              </span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                <span className="w-1.5 h-1.5 rounded-full bg-warning/50" />
                {strings.pools.busyByAdmin} {heldSlots}
              </span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                <span className="w-1.5 h-1.5 rounded-full bg-accent/40" />
                {strings.pools.reservedShort} {reservedSlots}
              </span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                {/* Not "Offline": this bucket also holds phones reporting 'unknown' and
                    ones an operator withheld from sale while they are still online. What
                    they share is that none of them can be sold. */}
                <span className="w-1.5 h-1.5 rounded-full bg-text-3" />Unavailable{" "}
                {unavailableSlots}
              </span>
            </div>
        </div>
        </div>
      )}

      {/* Filters — same shape as every other list in the console. No date range here:
          a device card shows no date, so a from/to filter would have nothing on screen
          to check itself against. */}
      <div className="mb-4">
        <FilterBar
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder={strings.pools.searchPlaceholder}
          isFiltered={isFiltered}
          onClear={clearAll}
        >
          <FilterPill
            label={strings.pools.filterCity}
            value={city}
            onChange={setCity}
            options={cityOptions.map((c) => ({ value: c, label: c }))}
            allLabel={strings.common.all}
          />
          <FilterPill
            label={strings.pools.filterCarrier}
            value={carrier}
            onChange={setCarrier}
            options={carrierOptions.map((c) => ({ value: c, label: c }))}
            allLabel={strings.common.all}
          />
          <FilterPill
            label="Status"
            value={onlineOnly ? "online" : ""}
            onChange={(v) => setOnlineOnly(v === "online")}
            options={[{ value: "online", label: strings.pools.filterOnline }]}
            allLabel={strings.common.all}
          />
          <FilterPill
            label="Listed"
            value={sellableOnly ? "yes" : ""}
            onChange={(v) => setSellableOnly(v === "yes")}
            options={[{ value: "yes", label: strings.pools.filterSellable }]}
            allLabel={strings.common.all}
          />
        </FilterBar>
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

function SummaryCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "accent" | "success" | "warning";
}) {
  const toneClass =
    tone === "accent"
      ? "text-accent"
      : tone === "success"
        ? "text-success"
        : tone === "warning"
          ? "text-warning"
          : "text-text";
  return (
    // Every cell the same width regardless of its label or how many digits it holds:
    // they read as one row of comparable numbers, and the row does not reflow when a
    // count crosses into double figures. The width is set by the longest label — "Held in
    // iproxy" — because a label that wraps to a second line pushes its number below the
    // others, and five numbers meant to be compared have to sit on one line.
    <div className="flex flex-1 min-w-[156px] flex-col gap-0.5 px-5 py-3.5 border-l border-border first:border-l-0">
      <span className="whitespace-nowrap text-[.69rem] uppercase tracking-[.08em] text-text-3">
        {label}
      </span>
      <span className={`font-mono tabular-nums text-[1.55rem] font-semibold leading-none tracking-[-0.02em] ${toneClass}`}>
        <Num value={value} />
      </span>
    </div>
  );
}
