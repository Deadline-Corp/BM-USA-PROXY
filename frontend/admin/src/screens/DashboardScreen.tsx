import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { LinkButton } from "@/shared/components/LinkButton";
import { StatCard, StatClusterRow } from "@/shared/components/StatCard";
import { StatHero } from "@/shared/components/StatHero";
import { Num } from "@/shared/components/Num";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import {
  IconAlertTriangle,
  IconClock,
  IconCreditCard,
  IconPackages,
  IconRefresh,
  IconRequests,
  IconWallet,
} from "@/shared/components/icons";
import { useDashboardRevenue, useDashboardSummary } from "@/shared/hooks/useDashboard";
import { usePoolSummary } from "@/shared/hooks/usePool";
import { strings } from "@/shared/strings";
import { PoolMap } from "@/screens/dashboard/PoolMap";
import { useQueryClient } from "@tanstack/react-query";

export function DashboardScreen() {
  const qc = useQueryClient();
  const summaryQuery = useDashboardSummary();
  const revenueQuery = useDashboardRevenue(7);
  const poolQuery = usePoolSummary();

  const summary = summaryQuery.data;
  const revenuePoints = revenueQuery.data ?? [];
  const weekTotal = revenuePoints.reduce((acc, p) => acc + p.revenue, 0);
  const sparkline = revenuePoints.map((p) => p.revenue);
  const maxRevenue = Math.max(1, ...sparkline);
  const normalizedSpark = sparkline.map((v) => v / maxRevenue);

  function refreshAll() {
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    qc.invalidateQueries({ queryKey: ["pool"] });
  }

  return (
    <div>
      <PageHead
        title={strings.dashboard.title}
        subtitle={strings.dashboard.subtitle}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={refreshAll}>
              <IconRefresh />
              {strings.common.refresh}
            </Button>
            <LinkButton variant="primary" size="sm" to="/requests">
              <IconRequests className="w-4 h-4" />
              {strings.dashboard.reviewQueue}
            </LinkButton>
          </>
        }
      />

      {/* KPI row: hero revenue block + 5-up cluster */}
      <div className="grid grid-cols-[minmax(280px,1.15fr)_2fr] gap-4 mb-4 max-[1100px]:grid-cols-1">
        {summaryQuery.isLoading ? (
          <Skeleton className="h-[190px] rounded-lg" />
        ) : (
          <StatHero
            label={strings.dashboard.revenue7d}
            value={<Num value={weekTotal} usd />}
            deltaPct={12}
            deltaLabel={strings.dashboard.vsPriorWeek}
            sparkline={normalizedSpark.length > 1 ? normalizedSpark : undefined}
            sparklineLabels={revenuePoints.length > 1 ? ["", "", "", "", "", "", ""] : undefined}
          />
        )}

        {summaryQuery.isLoading || !summary ? (
          <Skeleton className="h-[190px] rounded-lg" />
        ) : (
          <StatClusterRow className="grid-cols-2 min-[1101px]:!grid-cols-5">
            <StatCard
              icon={<IconPackages />}
              label={strings.dashboard.activeAccesses}
              value={<Num value={summary.active_accesses} />}
              footer="across all carriers"
            />
            <StatCard
              icon={<IconClock />}
              label="Free pool slots"
              value={<Num value={summary.free_pool} />}
              footer="ready to auto-issue"
            />
            <StatCard
              icon={<IconRequests />}
              label={strings.dashboard.newRequests}
              value={<Num value={summary.new_requests} />}
              footer={
                <Link to="/requests" className="text-accent font-semibold hover:text-accent-2">
                  {strings.dashboard.reviewQueue}
                </Link>
              }
            />
            <StatCard
              icon={<IconWallet />}
              label={strings.dashboard.pendingReview}
              value={<Num value={summary.pending_manual_review} />}
              footer={
                <Link to="/orders" className="text-accent font-semibold hover:text-accent-2">
                  Review payments
                </Link>
              }
            />
            <StatCard
              icon={<IconCreditCard />}
              label="Revenue (30d)"
              value={<Num value={summary.revenue.d30} usd />}
              footer="rolling 30 days"
            />
          </StatClusterRow>
        )}
      </div>

      {/* Signature hero: USA pool map */}
      <Panel className="relative overflow-hidden">
        <Panel.Head
          title={strings.dashboard.mapTitle}
          subtitle="Real-device 5G nodes across US carriers"
          actions={
            <LinkButton variant="ghost" size="sm" to="/pools">
              {strings.dashboard.managePools}
            </LinkButton>
          }
        />
        <div className="px-1.5 pt-1.5">
          {poolQuery.isLoading ? (
            <Skeleton className="h-[300px]" />
          ) : poolQuery.isError ? (
            <ErrorState onRetry={() => poolQuery.refetch()} />
          ) : (
            <PoolMap cities={poolQuery.data?.cities ?? []} />
          )}
        </div>
        <div className="flex items-center gap-[18px] flex-wrap px-[18px] py-3.5 border-t border-border">
          <span className="flex items-center gap-1.5 text-[.78rem] text-text-2">
            <span className="w-2 h-2 rounded-full bg-success inline-block" />
            Online
          </span>
          <span className="flex items-center gap-1.5 text-[.78rem] text-text-2">
            <span className="w-2 h-2 rounded-full bg-warning inline-block" />
            Full capacity
          </span>
          <span className="flex items-center gap-1.5 text-[.78rem] text-text-2">
            <span className="w-2 h-2 rounded-full bg-text-3 inline-block" />
            Offline
          </span>
          <div className="ml-auto flex items-center gap-[18px]">
            <TotalStat label="Slots" value={poolQuery.data?.slots_total ?? 0} />
            <TotalStat label="Used" value={poolQuery.data?.slots_used ?? 0} />
            <TotalStat label="Free" value={poolQuery.data?.slots_free ?? 0} />
          </div>
        </div>
      </Panel>

      {/* Lower: needs attention + activity */}
      <div className="grid grid-cols-[1.1fr_1fr_1fr] gap-4 mt-4 max-[1180px]:grid-cols-1">
        <Panel>
          <Panel.Head title={strings.dashboard.needsAttention} subtitle={`${summary?.pending_manual_review ?? 0} items`} />
          <div className="flex flex-col">
            {!summary ? (
              <Skeleton className="h-32 m-4" />
            ) : summary.pending_manual_review === 0 && summary.new_requests === 0 ? (
              <EmptyState title="All clear" hint="Nothing needs operator attention right now." icon={<IconAlertTriangle className="w-5 h-5" />} />
            ) : (
              <>
                {summary.pending_manual_review > 0 && (
                  <AttentionRow
                    icon={<IconWallet className="w-[17px] h-[17px]" />}
                    tone="warn"
                    title={`${summary.pending_manual_review} payment(s) in manual review`}
                    sub="Amount mismatch or unrecognized sender"
                    action={<LinkButton variant="ghost" size="sm" to="/orders">Review</LinkButton>}
                  />
                )}
                {summary.new_requests > 0 && (
                  <AttentionRow
                    icon={<IconRequests className="w-[17px] h-[17px]" />}
                    tone="accent"
                    title={`${summary.new_requests} new request(s)`}
                    sub="Awaiting first response"
                    action={<LinkButton variant="ghost" size="sm" to="/requests">Open</LinkButton>}
                  />
                )}
              </>
            )}
          </div>
        </Panel>

        <Panel className="col-span-1 min-[1181px]:col-span-2">
          <Panel.Head title={strings.dashboard.revenueTrend} subtitle="Last 7 days" />
          <div className="p-[18px] pt-2 h-[220px]">
            {revenueQuery.isLoading ? (
              <Skeleton className="h-full" />
            ) : revenuePoints.length === 0 ? (
              <EmptyState title="No revenue yet" hint="Chart fills in as orders complete." />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={revenuePoints} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="revFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#195079" stopOpacity={0.18} />
                      <stop offset="100%" stopColor="#195079" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="date"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 11, fill: "#7C95A8", fontFamily: "Roboto Mono" }}
                    tickFormatter={(v: string) => new Date(v).toLocaleDateString("en-US", { weekday: "short" })}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#FFFFFF",
                      border: "1px solid #D8E6F0",
                      borderRadius: 10,
                      fontSize: 12,
                      fontFamily: "Roboto",
                    }}
                    formatter={(value: number) => [`$${value.toFixed(2)}`, "Revenue"]}
                    labelFormatter={(label: string) => new Date(label).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  />
                  <Area
                    type="monotone"
                    dataKey="revenue"
                    stroke="#195079"
                    strokeWidth={2}
                    fill="url(#revFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function TotalStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col items-end">
      <span className="font-mono tabular-nums text-[1.05rem] font-semibold text-text leading-none">
        <Num value={value} />
      </span>
      <span className="text-[.68rem] uppercase tracking-[.08em] text-text-3 mt-[3px]">{label}</span>
    </div>
  );
}

function AttentionRow({
  icon,
  tone,
  title,
  sub,
  action,
}: {
  icon: React.ReactNode;
  tone: "warn" | "alert" | "accent";
  title: string;
  sub: string;
  action?: React.ReactNode;
}) {
  const toneClass = {
    warn: "text-warning",
    alert: "text-danger",
    accent: "text-accent",
  }[tone];
  return (
    <div className="flex items-center gap-[13px] px-[18px] py-[13px] border-b border-border last:border-b-0 hover:bg-surface-2 transition-colors duration-150 ease-brand">
      <div className={`w-[34px] h-[34px] flex-none rounded-[9px] bg-surface-2 border border-border-2 grid place-items-center ${toneClass}`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[.88rem] text-text font-medium truncate">{title}</div>
        <div className="text-[.78rem] text-text-3 mt-0.5 truncate">{sub}</div>
      </div>
      {action && <div className="flex-none">{action}</div>}
    </div>
  );
}
