import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ShieldCheck,
  MapPin,
  RefreshCw,
  CalendarPlus,
  ArrowLeftRight,
  ChevronDown,
  FileDown,
  Copy,
  Check,
} from "lucide-react";
import {
  useAccessDetail,
  useRotateIp,
  useSwapAccess,
  useExtendAccess,
  useRequestConfig,
  isRetryAfterError,
  getRetryAfterSeconds,
} from "../shared/hooks/useAccesses";
import { useCatalog } from "../shared/hooks/useCatalog";
import { useToast } from "../shared/components/Toast";
import { useTermsGate } from "../shared/hooks/useTermsGate";
import { strings } from "../shared/strings";
import { SectionLabel } from "../shared/components/Card";
import { Chip, Dot } from "../shared/components/Chip";
import { Button } from "../shared/components/Button";
import { Num } from "../shared/components/Num";
import { CopyField } from "../shared/components/CopyField";
import { CountdownBadge } from "../shared/components/CountdownBadge";
import { Sheet } from "../shared/components/Sheet";
import { CredentialRowsSkeleton } from "../shared/components/Skeleton";
import { ErrorState } from "../shared/components/ErrorState";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { maskSecret } from "../shared/lib/format";
import { cacheInvoice } from "../shared/lib/invoiceCache";
import type { Carrier, ConfigType } from "../shared/api/types";

const ANY = "any" as const;

export function AccessDetailScreen() {
  const { publicId } = useParams<{ publicId: string }>();
  const navigate = useNavigate();
  const detailQuery = useAccessDetail(publicId);
  const catalogQuery = useCatalog();
  const rotateIp = useRotateIp(publicId);
  const swapAccess = useSwapAccess(publicId);
  const extendAccess = useExtendAccess(publicId);
  const requestConfig = useRequestConfig(publicId);
  const { showToast } = useToast();
  const termsGate = useTermsGate();
  const { copied: pwCopied, copy: copyPassword } = useCopyToClipboard();
  const { copied: allCopied, copy: copyAll } = useCopyToClipboard();

  const [passwordRevealed, setPasswordRevealed] = useState(false);
  const [rotateCooldownUntil, setRotateCooldownUntil] = useState<number | null>(null);
  const [rotateCooldownRemaining, setRotateCooldownRemaining] = useState(0);
  const [rotateConfirmOpen, setRotateConfirmOpen] = useState(false);
  const [swapSheetOpen, setSwapSheetOpen] = useState(false);
  const [swapConfirmOpen, setSwapConfirmOpen] = useState(false);
  const [swapLocationId, setSwapLocationId] = useState<number | typeof ANY>(ANY);
  const [swapCarrier, setSwapCarrier] = useState<Carrier | typeof ANY>(ANY);
  const [extendSheetOpen, setExtendSheetOpen] = useState(false);
  const [howToOpen, setHowToOpen] = useState(false);

  useEffect(() => {
    if (rotateCooldownUntil === null) return;
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((rotateCooldownUntil - Date.now()) / 1000));
      setRotateCooldownRemaining(remaining);
      if (remaining <= 0) setRotateCooldownUntil(null);
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [rotateCooldownUntil]);

  async function handleRotate() {
    setRotateConfirmOpen(false);
    try {
      await rotateIp.mutateAsync();
      showToast("IP rotated");
    } catch (error) {
      if (isRetryAfterError(error)) {
        const seconds = getRetryAfterSeconds(error);
        setRotateCooldownUntil(Date.now() + seconds * 1000);
      }
    }
  }

  async function handleSwap() {
    setSwapConfirmOpen(false);
    await swapAccess.mutateAsync({
      location_id: swapLocationId === ANY ? undefined : swapLocationId,
      carrier: swapCarrier === ANY ? undefined : swapCarrier,
    });
    showToast("Location swapped");
  }

  async function handleExtend(tariffCode: string) {
    setExtendSheetOpen(false);
    try {
      const response = await termsGate(() => extendAccess.mutateAsync({ tariff_code: tariffCode }));
      cacheInvoice(response.order.public_id, response.invoice);
      navigate(`/checkout/${response.order.public_id}`);
    } catch {
      // termsGate already redirected on 428; other errors surface via extendAccess.isError below.
    }
  }

  async function handleRequestConfig(type: ConfigType) {
    await requestConfig.mutateAsync({ type });
    showToast(strings.access.configSentToast);
  }

  if (detailQuery.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-48 animate-pulse rounded-xl bg-surface-2" />
        <CredentialRowsSkeleton />
      </div>
    );
  }

  if (detailQuery.isError || !detailQuery.data) {
    return <ErrorState message={strings.errors.accessNotFound} onRetry={() => detailQuery.refetch()} />;
  }

  const access = detailQuery.data;
  const combined = `${access.credentials.host ?? ""}:${access.credentials.socks5_port ?? ""}:${
    access.credentials.login ?? ""
  }:${access.credentials.password ?? ""}`;

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
          <ShieldCheck size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[15.5px] font-semibold leading-tight tracking-tight text-text">
            {access.city ?? strings.access.title}
          </b>
          <span className="text-xs text-text-3">{[access.state_code, access.carrier].filter(Boolean).join(" · ")}</span>
        </div>
        <Chip tone={access.status === "active" ? "success" : "default"}>
          <Dot tone={access.status === "active" ? "online" : "idle"} />
          {access.status === "active" ? strings.home.online : access.status}
        </Chip>
      </div>

      {/* ── hero ── */}
      <SectionLabel>{strings.access.activeLabel}</SectionLabel>
      <div className="rounded-xl border border-border bg-gradient-to-b from-accent/[.06] to-transparent to-70% bg-surface p-[17px] shadow">
        <div className="flex items-start justify-between gap-2.5">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
              <MapPin size={19} strokeWidth={1.5} aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <b className="block truncate font-head text-[16px] font-semibold leading-tight tracking-tight text-text">
                {access.city ?? "—"}
              </b>
              <span className="text-xs text-text-3">
                {[access.state_code, access.carrier].filter(Boolean).join(" · ")}
              </span>
            </div>
          </div>
        </div>

        <div className="mt-3.5">
          <div className="mb-1.5 flex items-baseline justify-between text-xs text-text-3">
            <span>{strings.common.expiresIn}</span>
            <CountdownBadge expiresAt={access.expires_at} valueClassName="text-[13px]" />
          </div>
          <div className="h-[3px] overflow-hidden rounded-full bg-surface-2">
            <div className="h-full w-1/4 rounded-full bg-warning transition-[width] duration-500 ease-out" />
          </div>
        </div>

        <div className="mt-3.5 flex gap-2.5">
          <Button
            variant="primary"
            block
            disabled={rotateIp.isPending || rotateCooldownRemaining > 0}
            onClick={() => setRotateConfirmOpen(true)}
          >
            <RefreshCw size={15} aria-hidden="true" />
            {rotateCooldownRemaining > 0
              ? `${strings.access.rotateCoolingPrefix} (${rotateCooldownRemaining}s)`
              : strings.access.rotateIp}
          </Button>
          <Button variant="default" block onClick={() => setExtendSheetOpen(true)}>
            <CalendarPlus size={15} aria-hidden="true" />
            {strings.access.extend}
          </Button>
        </div>

        {access.swap_left > 0 ? (
          <Button variant="ghost" block className="mt-2" onClick={() => setSwapSheetOpen(true)}>
            <ArrowLeftRight size={15} aria-hidden="true" />
            {strings.access.swap} (<Num>{access.swap_left}</Num> {strings.access.swapLeft})
          </Button>
        ) : null}

        <p className="mt-1.5 text-center text-[11px] leading-relaxed text-text-3">{strings.access.rotateNote}</p>
      </div>

      {/* ── credentials ── */}
      <SectionLabel className="mt-[18px]">{strings.access.credentialsLabel}</SectionLabel>
      <div className="flex flex-col gap-1.5">
        <CopyField label={strings.access.hostLabel} value={access.credentials.host ?? "—"} />
        <CopyField
          label={strings.access.socksPortLabel}
          value={access.credentials.socks5_port?.toString() ?? "—"}
        />
        <CopyField label={strings.access.loginLabel} value={access.credentials.login ?? "—"} />
        <div className="flex items-center gap-0 h-11 overflow-hidden rounded border border-border bg-surface">
          <span className="flex h-full w-[58px] shrink-0 items-center border-r border-border bg-surface-2 px-2.5 font-mono text-[10px] uppercase tracking-wide text-text-3">
            {strings.access.passLabel}
          </span>
          <span className="num flex-1 overflow-hidden text-ellipsis whitespace-nowrap px-2.5 text-[13px] text-text">
            {access.credentials.password
              ? passwordRevealed
                ? access.credentials.password
                : maskSecret(access.credentials.password)
              : "—"}
          </span>
          <button
            type="button"
            className="flex h-full shrink-0 items-center justify-center border-l border-border px-2.5 text-[11px] font-medium text-text-2 transition-colors hover:text-accent"
            onClick={() => setPasswordRevealed((v) => !v)}
          >
            {passwordRevealed ? strings.common.hide : strings.common.reveal}
          </button>
          <button
            type="button"
            className="flex h-full w-11 shrink-0 items-center justify-center border-l border-border text-text-3 transition-colors duration-150 ease-out hover:bg-accent/[.08] hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            aria-label="Copy password"
            onClick={() => access.credentials.password && copyPassword(access.credentials.password)}
          >
            {pwCopied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      {/* ── combined copy ── */}
      <div className="mt-2 flex items-center gap-2.5 rounded border border-border-2 bg-surface p-3">
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 text-[10px] uppercase tracking-wide text-text-3">{strings.access.combinedLabel}</div>
          <Num className="block overflow-hidden text-ellipsis whitespace-nowrap text-[11px] text-text-2">
            {combined}
          </Num>
        </div>
        <button
          type="button"
          className="flex h-[38px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[8px] border border-border-2 bg-transparent px-3.5 text-xs font-medium text-accent transition-colors hover:bg-accent/[.08] hover:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          onClick={() => copyAll(combined)}
        >
          {allCopied ? <Check size={14} /> : <Copy size={14} />}
          {strings.common.copyAll}
        </button>
      </div>

      {/* ── config buttons ── */}
      <div className="mt-3 flex gap-2">
        {access.configs_available.includes("ovpn") ? (
          <Button
            variant="default"
            block
            disabled={requestConfig.isPending}
            onClick={() => handleRequestConfig("ovpn")}
          >
            <FileDown size={15} aria-hidden="true" />
            {strings.access.configOvpn}
          </Button>
        ) : null}
        {access.configs_available.includes("wg") ? (
          <Button
            variant="default"
            block
            disabled={requestConfig.isPending}
            onClick={() => handleRequestConfig("wg")}
          >
            <FileDown size={15} aria-hidden="true" />
            {strings.access.configWg}
          </Button>
        ) : null}
      </div>

      {/* ── how to connect ── */}
      <button
        type="button"
        className="mt-3.5 flex items-center justify-between gap-2 rounded-[8px] px-2 py-2.5 text-[13px] font-medium text-accent transition-colors hover:bg-surface-2"
        onClick={() => setHowToOpen((v) => !v)}
        aria-expanded={howToOpen}
      >
        <span>{strings.access.howToConnect}</span>
        <ChevronDown size={15} className={`transition-transform ${howToOpen ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {howToOpen ? (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3.5">
          <HowToRow title={strings.access.howToConnectSocks} body={strings.access.howToConnectSocksBody} />
          <HowToRow title={strings.access.howToConnectHttp} body={strings.access.howToConnectHttpBody} />
          <HowToRow title={strings.access.howToConnectOvpn} body={strings.access.howToConnectOvpnBody} />
          <HowToRow title={strings.access.howToConnectWg} body={strings.access.howToConnectWgBody} />
        </div>
      ) : null}

      {/* ── rotate confirm ── */}
      <Sheet
        open={rotateConfirmOpen}
        onClose={() => setRotateConfirmOpen(false)}
        title={strings.access.rotateConfirmTitle}
        footer={
          <Button variant="primary" block disabled={rotateIp.isPending} onClick={handleRotate}>
            {strings.access.rotateIp}
          </Button>
        }
      >
        <p className="text-[13px] leading-relaxed text-text-2">{strings.access.rotateConfirmBody}</p>
      </Sheet>

      {/* ── swap sheet ── */}
      <Sheet open={swapSheetOpen} onClose={() => setSwapSheetOpen(false)} title={strings.access.swapSheetTitle}>
        <div className="flex flex-col gap-4">
          <div>
            <p className="mb-1.5 text-xs font-medium text-text-2">{strings.catalog.citySelectorLabel}</p>
            <div className="flex flex-col gap-1">
              <PickerRow
                label={strings.common.any}
                selected={swapLocationId === ANY}
                onSelect={() => setSwapLocationId(ANY)}
              />
              {catalogQuery.data?.locations.map((loc) => (
                <PickerRow
                  key={loc.id}
                  label={`${loc.city}, ${loc.state_code}`}
                  selected={swapLocationId === loc.id}
                  onSelect={() => setSwapLocationId(loc.id)}
                />
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-xs font-medium text-text-2">{strings.catalog.carrierSelectorLabel}</p>
            <div className="flex flex-col gap-1">
              <PickerRow label={strings.common.any} selected={swapCarrier === ANY} onSelect={() => setSwapCarrier(ANY)} />
              {catalogQuery.data?.carriers.map((c) => (
                <PickerRow key={c} label={c} selected={swapCarrier === c} onSelect={() => setSwapCarrier(c)} />
              ))}
            </div>
          </div>
          <Button
            variant="primary"
            block
            onClick={() => {
              setSwapSheetOpen(false);
              setSwapConfirmOpen(true);
            }}
          >
            {strings.common.confirm}
          </Button>
        </div>
      </Sheet>

      {/* ── swap confirm ── */}
      <Sheet
        open={swapConfirmOpen}
        onClose={() => setSwapConfirmOpen(false)}
        title={strings.access.swapConfirmTitle}
        footer={
          <Button variant="primary" block disabled={swapAccess.isPending} onClick={handleSwap}>
            {strings.access.swap}
          </Button>
        }
      >
        <p className="text-[13px] leading-relaxed text-text-2">{strings.access.swapConfirmBody}</p>
      </Sheet>

      {/* ── extend sheet ── */}
      <Sheet open={extendSheetOpen} onClose={() => setExtendSheetOpen(false)} title={strings.access.extendSheetTitle}>
        <div className="flex flex-col gap-1.5">
          {catalogQuery.data?.tariffs
            .filter((t) => t.code !== "trial")
            .map((tariff) => (
              <button
                key={tariff.code}
                type="button"
                className="flex items-center justify-between gap-2 rounded border border-border bg-surface px-3.5 py-3 text-left transition-colors hover:border-accent hover:bg-accent/[.05]"
                onClick={() => handleExtend(tariff.code)}
                disabled={extendAccess.isPending}
              >
                <span>
                  <b className="block text-[13.5px] font-medium text-text">{tariff.name}</b>
                  <small className="text-[11.5px] text-text-3">{tariff.description}</small>
                </span>
                <Num className="text-[15px] font-semibold text-accent">${tariff.price_usd.toFixed(2)}</Num>
              </button>
            ))}
        </div>
      </Sheet>
    </div>
  );
}

function HowToRow({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[8px] bg-surface-2 px-2.5 py-2">
      <b className="num block text-[11.5px] text-text">{title}</b>
      <small className="text-[11px] leading-snug text-text-3">{body}</small>
    </div>
  );
}

function PickerRow({ label, selected, onSelect }: { label: string; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      className={`rounded px-3 py-2.5 text-left text-[13.5px] transition-colors ${
        selected ? "bg-accent/[.08] text-accent" : "text-text hover:bg-surface-2"
      }`}
      onClick={onSelect}
    >
      {label}
    </button>
  );
}
