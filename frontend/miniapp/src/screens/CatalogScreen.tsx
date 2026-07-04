import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LayoutGrid, MapPin, Radio, Send, Briefcase, Users, MessageCircle, ChevronRight } from "lucide-react";
import { useCatalog } from "../shared/hooks/useCatalog";
import { useCreateOrder } from "../shared/hooks/useOrder";
import { useCreateRequest } from "../shared/hooks/useRequests";
import { useTermsGate } from "../shared/hooks/useTermsGate";
import { useRequireTos } from "../shared/hooks/useRequireTos";
import { useToast } from "../shared/components/Toast";
import { strings } from "../shared/strings";
import { SectionLabel } from "../shared/components/Card";
import { Chip } from "../shared/components/Chip";
import { Button } from "../shared/components/Button";
import { Num } from "../shared/components/Num";
import { TariffCard } from "../shared/components/TariffCard";
import { Sheet } from "../shared/components/Sheet";
import { TariffListSkeleton } from "../shared/components/Skeleton";
import { ErrorState } from "../shared/components/ErrorState";
import { EmptyState } from "../shared/components/EmptyState";
import { ApiError } from "../shared/api/client";
import { formatUsd } from "../shared/lib/format";
import { cacheInvoice } from "../shared/lib/invoiceCache";
import type { Carrier, Tariff } from "../shared/api/types";

const ANY = "any" as const;

export function CatalogScreen() {
  const catalogQuery = useCatalog();
  const createOrder = useCreateOrder();
  const createRequest = useCreateRequest();
  const termsGate = useTermsGate();
  const requireTos = useRequireTos();
  const { showToast } = useToast();
  const navigate = useNavigate();

  const [locationId, setLocationId] = useState<number | typeof ANY>(ANY);
  const [carrier, setCarrier] = useState<Carrier | typeof ANY>(ANY);
  const [citySheetOpen, setCitySheetOpen] = useState(false);
  const [carrierSheetOpen, setCarrierSheetOpen] = useState(false);
  const [resellerSheetOpen, setResellerSheetOpen] = useState(false);
  const [resellerMessage, setResellerMessage] = useState("");
  const [orderError, setOrderError] = useState<string | null>(null);
  const [pendingTariff, setPendingTariff] = useState<string | null>(null);

  const selectedLocation = useMemo(
    () => (locationId === ANY ? null : catalogQuery.data?.locations.find((l) => l.id === locationId) ?? null),
    [locationId, catalogQuery.data],
  );

  async function handleBuy(tariff: Tariff) {
    if (!requireTos()) return;
    setOrderError(null);
    setPendingTariff(tariff.code);
    try {
      const response = await termsGate(() =>
        createOrder.mutateAsync({
          tariff_code: tariff.code,
          location_id: locationId === ANY ? undefined : locationId,
          carrier: carrier === ANY ? undefined : carrier,
        }),
      );
      cacheInvoice(response.order.public_id, response.invoice);
      navigate(`/checkout/${response.order.public_id}`);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 409) setOrderError(strings.errors.soldOut);
        else if (error.status === 422) setOrderError(strings.errors.trialUsed);
        else if (error.status !== 428) setOrderError(error.message);
      } else {
        setOrderError(strings.errors.generic);
      }
    } finally {
      setPendingTariff(null);
    }
  }

  async function handleResellerSubmit() {
    try {
      await createRequest.mutateAsync({
        type: "reseller",
        subject: strings.catalog.resellerFormSubject,
        body: resellerMessage,
      });
      setResellerSheetOpen(false);
      setResellerMessage("");
      showToast(strings.catalog.resellerFormSent);
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : strings.errors.generic, "error");
    }
  }

  const trialTariff = catalogQuery.data?.tariffs.find((t) => t.code === "trial");
  const otherTariffs = catalogQuery.data?.tariffs.filter((t) => t.code !== "trial") ?? [];
  const bestValueCode = otherTariffs.reduce<string | null>((bestCode, t) => {
    if (!bestCode) return t.code;
    const best = otherTariffs.find((x) => x.code === bestCode);
    return best && t.duration_minutes > best.duration_minutes ? t.code : bestCode;
  }, null);

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
          <LayoutGrid size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[15.5px] font-semibold leading-tight tracking-tight text-text">
            {strings.catalog.title}
          </b>
          <span className="text-xs text-text-3">{strings.app.tagline}</span>
        </div>
      </div>

      {/* ── city / carrier selectors ── */}
      <div className="mb-4 flex gap-2">
        <button
          type="button"
          className="flex flex-1 items-center justify-between gap-2 rounded border border-border bg-surface px-3 py-2.5 text-left text-[13px] text-text transition-colors hover:border-border-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          onClick={() => setCitySheetOpen(true)}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <MapPin size={14} className="shrink-0 text-text-3" aria-hidden="true" />
            <span className="truncate">{selectedLocation ? selectedLocation.city : strings.common.any}</span>
          </span>
          <ChevronRight size={14} className="shrink-0 text-text-3" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="flex flex-1 items-center justify-between gap-2 rounded border border-border bg-surface px-3 py-2.5 text-left text-[13px] text-text transition-colors hover:border-border-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          onClick={() => setCarrierSheetOpen(true)}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <Radio size={14} className="shrink-0 text-text-3" aria-hidden="true" />
            <span className="truncate">{carrier === ANY ? strings.common.any : carrier}</span>
          </span>
          <ChevronRight size={14} className="shrink-0 text-text-3" aria-hidden="true" />
        </button>
      </div>

      {orderError ? (
        <div className="mb-3">
          <ErrorState message={orderError} compact />
        </div>
      ) : null}

      <SectionLabel>{strings.catalog.choosePlan}</SectionLabel>

      {catalogQuery.isLoading ? (
        <TariffListSkeleton />
      ) : catalogQuery.isError ? (
        <ErrorState message={strings.errors.generic} onRetry={() => catalogQuery.refetch()} />
      ) : !catalogQuery.data || catalogQuery.data.tariffs.length === 0 ? (
        <EmptyState icon={<LayoutGrid size={22} strokeWidth={1.5} />} title={strings.catalog.needHelp} />
      ) : (
        <div className="flex flex-col gap-2.5">
          {trialTariff ? (
            <TariffCard
              name={strings.catalog.trialName}
              meta={strings.catalog.trialMeta}
              price={strings.catalog.free}
              priceSub={`${trialTariff.duration_minutes} min`}
              isFree
              features={[trialTariff.description]}
              action={
                <Button
                  variant={catalogQuery.data.trial_available ? "primary" : "ghost"}
                  block
                  disabled={!catalogQuery.data.trial_available || pendingTariff === trialTariff.code}
                  onClick={() => handleBuy(trialTariff)}
                >
                  {catalogQuery.data.trial_available
                    ? strings.catalog.trialCta
                    : strings.catalog.trialAlreadyUsed}
                </Button>
              }
            />
          ) : null}

          {otherTariffs.map((tariff) => {
            const highlight = tariff.code === bestValueCode;
            return (
              <TariffCard
                key={tariff.code}
                name={tariff.name}
                meta={tariff.description}
                price={<Num>{formatUsd(tariff.price_usd)}</Num>}
                priceSub={
                  tariff.duration_minutes >= 24 * 60 * 7
                    ? strings.catalog.perMonth
                    : tariff.duration_minutes >= 24 * 60
                      ? strings.catalog.perWeek
                      : strings.catalog.perDay
                }
                highlight={highlight}
                features={[tariff.description]}
                extraBadges={
                  highlight ? (
                    <Chip tone="accent" className="self-start text-[11px]">
                      {strings.catalog.bestValue}
                    </Chip>
                  ) : undefined
                }
                action={
                  <Button
                    variant="primary"
                    block
                    disabled={pendingTariff === tariff.code}
                    onClick={() => handleBuy(tariff)}
                  >
                    {strings.catalog.buyPrefix} {tariff.name} — <Num>{formatUsd(tariff.price_usd)}</Num>
                  </Button>
                }
              />
            );
          })}
        </div>
      )}

      {/* ── reseller ── */}
      <SectionLabel className="mt-[18px]">{strings.catalog.resellerTitle}</SectionLabel>
      <div className="flex items-center gap-3.5 rounded-lg border border-border bg-surface p-4 shadow-card">
        <span className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded border border-accent/[.22] bg-accent/10 text-accent">
          <Briefcase size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[14px] font-semibold leading-snug tracking-tight text-text">
            {strings.catalog.resellerTitle}
          </b>
          <small className="text-xs leading-snug text-text-3">{strings.catalog.resellerBody}</small>
        </div>
        <Button variant="primary" size="sm" className="whitespace-nowrap" onClick={() => setResellerSheetOpen(true)}>
          {strings.catalog.resellerCta}
        </Button>
      </div>

      {/* ── referral nudge ── */}
      <div className="mt-2.5 flex items-center gap-2.5 rounded border border-accent/[.22] bg-accent/[.08] px-3.5 py-2.5 text-xs text-text-2">
        <Users size={15} className="shrink-0 text-accent" aria-hidden="true" />
        <span>
          Refer a client &amp; earn <b className="text-accent">20%</b> of every payment, for life.
        </span>
      </div>

      {/* ── coverage ── */}
      {catalogQuery.data && catalogQuery.data.locations.length > 0 ? (
        <>
          <SectionLabel className="mt-[18px]">
            {strings.catalog.coverageLabel} — <Num>{catalogQuery.data.locations.length}</Num> US cities
          </SectionLabel>
          <div className="flex items-start gap-2.5 rounded border border-border bg-surface px-4 py-3.5">
            <MapPin size={16} className="mt-0.5 shrink-0 text-text-3" aria-hidden="true" />
            <div className="flex flex-1 flex-wrap gap-1.5">
              {catalogQuery.data.locations.map((loc) => (
                <span
                  key={loc.id}
                  className="rounded-md border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] text-text-3"
                >
                  {loc.city}, {loc.state_code}
                </span>
              ))}
            </div>
          </div>
        </>
      ) : null}

      {/* ── support links ── */}
      <SectionLabel className="mt-[18px]">{strings.catalog.needHelp}</SectionLabel>
      <div className="flex flex-col">
        <a
          href="https://t.me/usproxy_support"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 border-b border-border py-3 no-underline last:border-b-0"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-border bg-surface-2 text-text-2">
            <Send size={17} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <b className="block text-[13.5px] font-medium text-text">@usproxy_support</b>
            <small className="text-[11.5px] text-text-3">Free trial · all sales inquiries</small>
          </span>
          <ChevronRight size={15} className="shrink-0 text-text-3" aria-hidden="true" />
        </a>
        <a
          href="https://t.me/usproxyclub"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 border-b border-border py-3 no-underline last:border-b-0"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-border bg-surface-2 text-text-2">
            <MessageCircle size={17} strokeWidth={1.5} aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <b className="block text-[13.5px] font-medium text-text">@usproxyclub</b>
            <small className="text-[11.5px] text-text-3">BM USA PROXY CLUB · news &amp; updates</small>
          </span>
          <ChevronRight size={15} className="shrink-0 text-text-3" aria-hidden="true" />
        </a>
      </div>

      {/* ── city sheet ── */}
      <Sheet open={citySheetOpen} onClose={() => setCitySheetOpen(false)} title={strings.catalog.citySheetTitle}>
        <div className="flex flex-col gap-1">
          <CityRow
            label={strings.common.any}
            selected={locationId === ANY}
            freeCount={catalogQuery.data?.any_city_free.any}
            onSelect={() => {
              setLocationId(ANY);
              setCitySheetOpen(false);
            }}
          />
          {catalogQuery.data?.locations.map((loc) => (
            <CityRow
              key={loc.id}
              label={`${loc.city}, ${loc.state_code}`}
              selected={locationId === loc.id}
              freeCount={loc.free.any}
              onSelect={() => {
                setLocationId(loc.id);
                setCitySheetOpen(false);
              }}
            />
          ))}
        </div>
      </Sheet>

      {/* ── carrier sheet ── */}
      <Sheet
        open={carrierSheetOpen}
        onClose={() => setCarrierSheetOpen(false)}
        title={strings.catalog.carrierSheetTitle}
      >
        <div className="flex flex-col gap-1">
          <CityRow
            label={strings.common.any}
            selected={carrier === ANY}
            onSelect={() => {
              setCarrier(ANY);
              setCarrierSheetOpen(false);
            }}
          />
          {catalogQuery.data?.carriers.map((c) => (
            <CityRow
              key={c}
              label={c}
              selected={carrier === c}
              onSelect={() => {
                setCarrier(c);
                setCarrierSheetOpen(false);
              }}
            />
          ))}
        </div>
      </Sheet>

      {/* ── reseller request sheet ── */}
      <Sheet
        open={resellerSheetOpen}
        onClose={() => setResellerSheetOpen(false)}
        title={strings.catalog.resellerFormTitle}
        footer={
          <Button
            variant="primary"
            block
            disabled={resellerMessage.trim().length === 0 || createRequest.isPending}
            onClick={handleResellerSubmit}
          >
            {strings.common.submit}
          </Button>
        }
      >
        <label className="mb-1.5 block text-xs font-medium text-text-2" htmlFor="reseller-message">
          {strings.catalog.resellerFormBody}
        </label>
        <textarea
          id="reseller-message"
          className="min-h-[110px] w-full rounded border border-border bg-surface-2 p-3 font-body text-sm text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
          value={resellerMessage}
          onChange={(e) => setResellerMessage(e.target.value)}
        />
      </Sheet>
    </div>
  );
}

interface CityRowProps {
  label: string;
  selected: boolean;
  freeCount?: number;
  onSelect: () => void;
}

function CityRow({ label, selected, freeCount, onSelect }: CityRowProps) {
  const soldOut = freeCount === 0;
  return (
    <button
      type="button"
      className={`flex items-center justify-between gap-2 rounded px-3 py-2.5 text-left text-[13.5px] transition-colors ${
        selected ? "bg-accent/[.08] text-accent" : "text-text hover:bg-surface-2"
      }`}
      onClick={onSelect}
      disabled={soldOut}
    >
      <span className={soldOut ? "text-text-3" : undefined}>{label}</span>
      {freeCount !== undefined ? (
        soldOut ? (
          <span className="text-[11px] text-text-3">{strings.catalog.slotsSoldOut}</span>
        ) : (
          <span className="text-[11px] text-text-3">
            <Num>{freeCount}</Num> {strings.catalog.slotsFree}
          </span>
        )
      ) : null}
    </button>
  );
}
