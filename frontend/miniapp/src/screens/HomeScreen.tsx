import { Link } from "react-router-dom";
import {
  Zap,
  ShoppingBag,
  ShieldCheck,
  List,
  ChevronRight,
  Users,
  MapPin,
  Clock,
} from "lucide-react";
import { useMe } from "../shared/hooks/useMe";
import { BrandLogo } from "../shared/components/BrandLogo";
import { useActiveOrders } from "../shared/hooks/useOrder";
import { useAccesses } from "../shared/hooks/useAccesses";
import { useCatalog } from "../shared/hooks/useCatalog";
import { strings } from "../shared/strings";
import { Card, SectionLabel } from "../shared/components/Card";
import { Chip, Dot } from "../shared/components/Chip";
import { Button } from "../shared/components/Button";
import { Num } from "../shared/components/Num";
import { CountdownBadge } from "../shared/components/CountdownBadge";
import { HeroCardSkeleton, TileGridSkeleton } from "../shared/components/Skeleton";
import { ErrorState } from "../shared/components/ErrorState";
import { EmptyState } from "../shared/components/EmptyState";
import { formatCryptoAmount, formatUsd } from "../shared/lib/format";
import { useRequireTos } from "../shared/hooks/useRequireTos";

export function HomeScreen() {
  const meQuery = useMe();
  const accessesQuery = useAccesses();
  const catalogQuery = useCatalog();
  const requireTos = useRequireTos();

  const ordersQuery = useActiveOrders();
  const activeOrders = ordersQuery.data?.orders ?? [];
  const activeAccess = accessesQuery.data?.active[0] ?? null;
  const dailyTariff = catalogQuery.data?.tariffs.find((t) => t.duration_minutes === 24 * 60);
  const monthlyTariff = catalogQuery.data?.tariffs.reduce<typeof catalogQuery.data.tariffs[number] | undefined>(
    (best, t) => (!best || t.price_usd > best.price_usd ? t : best),
    undefined,
  );

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-5 flex items-center gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] bg-surface shadow-soft">
          <BrandLogo size={26} />
        </span>
        <div className="min-w-0 flex-1">
          {meQuery.isLoading ? (
            <div className="h-6 w-36 animate-pulse rounded bg-surface-2" />
          ) : meQuery.isError ? (
            <b className="block font-head text-[19px] font-extrabold leading-tight tracking-tight text-text">
              {strings.app.name}
            </b>
          ) : (
            <b className="block font-head text-[19px] font-extrabold leading-tight tracking-tight text-text">
              {meQuery.data?.first_name ?? strings.app.name}
            </b>
          )}
          <span className="text-[13px] text-text-2">{strings.app.tagline}</span>
        </div>
        {meQuery.data && meQuery.data.referral.available_usd > 0 ? (
          <div
            className="flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-[7px] text-xs text-text-2"
            title="Referral balance available"
          >
            <Users size={15} className="text-accent" aria-hidden="true" />
            <span>{strings.home.earnedBadge}</span>
            <Num className="text-[12.5px] font-medium text-text">
              {formatUsd(meQuery.data.referral.available_usd)}
            </Num>
          </div>
        ) : null}
      </div>

      {/* ── orders still in flight ──
          Sits above everything else on purpose: an unpaid order is the most urgent thing
          on this screen. Before this section a closed checkout tab was unrecoverable —
          the buyer could not see the address, the exact amount, or whether money already
          sent had been noticed. ── */}
      {activeOrders.length > 0 ? (
        <>
          <SectionLabel>{strings.home.activeOrdersLabel}</SectionLabel>
          <div className="mb-[18px] flex flex-col gap-2">
            {activeOrders.map((order) => {
              const awaiting = order.status === "awaiting_payment";
              return (
                <Link
                  key={order.public_id}
                  to={`/checkout/${order.public_id}`}
                  className="flex items-center gap-3 rounded-lg border border-warning/[.35] bg-warning/[.06] px-3.5 py-3 transition-colors duration-150 ease-out hover:border-warning focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <Clock size={18} className="shrink-0 text-warning" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <span className="block text-[15px] font-semibold text-text">
                      {awaiting
                        ? strings.home.orderAwaitingPayment
                        : strings.home.orderInProgress}
                    </span>
                    <small className="mt-0.5 block truncate text-[12.5px] text-text-3">
                      {order.invoice?.crypto_amount
                        ? `${formatCryptoAmount(order.invoice.crypto_amount)} ${order.invoice.crypto_currency ?? ""}`
                        : formatUsd(order.amount_usd)}
                      {" · "}
                      {order.tariff_code}
                    </small>
                  </div>
                  {awaiting && order.invoice ? (
                    <Chip tone="warn">
                      <CountdownBadge expiresAt={order.invoice.expires_at} />
                    </Chip>
                  ) : null}
                  <ChevronRight size={16} className="shrink-0 text-text-3" aria-hidden="true" />
                </Link>
              );
            })}
          </div>
        </>
      ) : null}

      {/* ── hero: active access or empty CTA ── */}
      <SectionLabel>{strings.home.heroLabel}</SectionLabel>
      {accessesQuery.isLoading ? (
        <HeroCardSkeleton />
      ) : accessesQuery.isError ? (
        <ErrorState message={strings.errors.generic} onRetry={() => accessesQuery.refetch()} />
      ) : activeAccess ? (
        <Card variant="hero">
          <div className="flex items-start justify-between gap-2.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
                <MapPin size={21} strokeWidth={1.5} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <b className="block truncate font-head text-[18px] font-bold leading-tight tracking-tight text-text">
                  {activeAccess.city ?? "—"}
                </b>
                <span className="text-[13px] text-text-3">
                  {[activeAccess.state_code, activeAccess.carrier].filter(Boolean).join(" · ")}
                </span>
              </div>
            </div>
            <Chip tone="success">
              <Dot tone="online" />
              {strings.home.online}
            </Chip>
          </div>

          <div className="mt-3.5 flex items-center justify-between rounded border border-border bg-surface-2 px-4 py-3">
            <span className="text-[12px] font-medium uppercase tracking-[.08em] text-text-3">
              {strings.common.expiresIn}
            </span>
            <CountdownBadge expiresAt={activeAccess.expires_at} variant="remaining" />
          </div>

          <div className="mt-3 flex gap-2.5">
            <Link to={`/access/${activeAccess.public_id}`} className="flex-1">
              <Button variant="primary" block>
                <ShieldCheck size={16} aria-hidden="true" />
                {strings.access.title}
              </Button>
            </Link>
          </div>
        </Card>
      ) : (
        <EmptyState
          icon={<Zap size={28} strokeWidth={1.5} />}
          title={strings.home.noAccessTitle}
          body={strings.home.noAccessBody}
          action={
            <Link to="/catalog">
              <Button variant="cta" onClick={() => requireTos()}>
                <Zap size={17} aria-hidden="true" />
                {strings.home.getProxyCta}
              </Button>
            </Link>
          }
        />
      )}

      {/* ── quick actions ── */}
      <SectionLabel className="mt-[18px]">{strings.home.quickActionsLabel}</SectionLabel>
      {catalogQuery.isLoading || accessesQuery.isLoading ? (
        <TileGridSkeleton />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <Link
            to="/catalog?tariff=trial"
            className="flex min-h-[116px] flex-col justify-between gap-4 rounded-lg border border-border/60 bg-surface p-4 text-left text-text shadow-soft transition-colors duration-150 ease-out hover:bg-surface-2 hover:border-border-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
              <Zap size={20} strokeWidth={1.5} aria-hidden="true" />
            </span>
            <span>
              <b className="block font-head text-[16px] font-bold leading-snug tracking-tight">
                {strings.home.tileTrialTitle}
              </b>
              <small className="mt-0.5 block text-[13px] text-text-3">
                {catalogQuery.data?.trial_available === false
                  ? strings.home.tileTrialSubUsed
                  : strings.home.tileTrialSubAvailable}
              </small>
            </span>
          </Link>

          <Link
            to="/catalog?tariff=daily"
            className="flex min-h-[116px] flex-col justify-between gap-4 rounded-lg border border-border/60 bg-surface p-4 text-left text-text shadow-soft transition-colors duration-150 ease-out hover:bg-surface-2 hover:border-border-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
              <ShoppingBag size={20} strokeWidth={1.5} aria-hidden="true" />
            </span>
            <span>
              <b className="block font-head text-[16px] font-bold leading-snug tracking-tight">
                {strings.home.tileDailyTitle}
              </b>
              <small className="mt-0.5 block text-[13px] text-text-3">
                {dailyTariff ? (
                  <>
                    <Num className="text-accent">{formatUsd(dailyTariff.price_usd)}</Num> ·{" "}
                    {strings.home.tileDailySub}
                  </>
                ) : (
                  strings.home.tileDailySub
                )}
              </small>
            </span>
          </Link>

          <Link
            to="/access"
            className="col-span-2 flex flex-row items-center gap-3.5 rounded-lg border border-border/60 bg-surface p-4 text-left text-text shadow-soft transition-colors duration-150 ease-out hover:bg-surface-2 hover:border-border-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
              <ShieldCheck size={20} strokeWidth={1.5} aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <b className="block font-head text-[16px] font-bold leading-snug tracking-tight">
                {strings.home.tileMyAccessTitle}
              </b>
              <small className="mt-0.5 block truncate text-[13px] text-text-3">
                {accessesQuery.data && accessesQuery.data.active.length > 0
                  ? `${accessesQuery.data.active.length} ${strings.home.tileMyAccessSubActive}`
                  : strings.home.tileMyAccessSubNone}
              </small>
            </span>
            <ChevronRight size={18} className="shrink-0 text-text-3" aria-hidden="true" />
          </Link>

          <Link
            to="/catalog"
            className="col-span-2 flex flex-row items-center gap-3.5 rounded-lg border border-border/60 bg-surface p-4 text-left text-text shadow-soft transition-colors duration-150 ease-out hover:bg-surface-2 hover:border-border-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
              <List size={20} strokeWidth={1.5} aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <b className="block font-head text-[16px] font-bold leading-snug tracking-tight">
                {strings.home.tileTariffsTitle}
              </b>
              <small className="mt-0.5 block truncate text-[13px] text-text-3">{strings.home.tileTariffsSub}</small>
            </span>
            {monthlyTariff ? (
              <Chip tone="accent">
                {monthlyTariff.name} <Num>{formatUsd(monthlyTariff.price_usd)}</Num>
              </Chip>
            ) : null}
          </Link>
        </div>
      )}

      {/* ── referral teaser ── */}
      {meQuery.data && meQuery.data.referral.available_usd > 0 ? (
        <>
          <SectionLabel className="mt-[18px]">{strings.home.referLabel}</SectionLabel>
          <div className="flex items-center gap-3.5 rounded-lg border border-border/60 bg-surface p-4 shadow-soft">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
              <Users size={20} strokeWidth={1.5} aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <b className="block font-head text-[16px] font-bold tracking-tight text-text">
                {strings.home.referTitle}
              </b>
              <small className="text-[13px] text-text-3">
                {strings.home.referSubtitle} ·{" "}
                <Num className="text-text-3">{formatUsd(meQuery.data.referral.available_usd)}</Num>{" "}
                {strings.home.referAvailableNow}
              </small>
            </div>
            <Link to="/referral">
              <Button variant="primary" size="sm">
                {strings.home.referInvite}
              </Button>
            </Link>
          </div>
        </>
      ) : null}
    </div>
  );
}
