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
  useSetAutoRotate,
  isRetryAfterError,
  getRetryAfterSeconds,
} from "../shared/hooks/useAccesses";
import { useCatalog } from "../shared/hooks/useCatalog";
import { useToast } from "../shared/components/Toast";
import { useTermsGate } from "../shared/hooks/useTermsGate";
import { strings } from "../shared/strings";
import { useCountdown } from "../shared/hooks/useCountdown";
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
import { ApiError } from "../shared/api/client";
import { formatCityState, formatTimeLeft, maskSecret } from "../shared/lib/format";
import { cacheInvoice } from "../shared/lib/invoiceCache";
import type { Carrier, ConfigType } from "../shared/api/types";

const ANY = "any" as const;

export function AccessDetailScreen() {
  const { publicId } = useParams<{ publicId: string }>();
  const navigate = useNavigate();
  const [rotating, setRotating] = useState(false);
  const [ipBeforeRotate, setIpBeforeRotate] = useState<string | null>(null);
  const detailQuery = useAccessDetail(publicId, { refetchInterval: rotating ? 4000 : false });
  const catalogQuery = useCatalog();
  const rotateIp = useRotateIp(publicId);
  const swapAccess = useSwapAccess(publicId);
  const extendAccess = useExtendAccess(publicId);
  const requestConfig = useRequestConfig(publicId);
  const { showToast } = useToast();
  const termsGate = useTermsGate();
  const { copied: allCopied, copy: copyAll } = useCopyToClipboard();
  const { copied: ipCopied, copy: copyIp } = useCopyToClipboard();

  const [rotateCooldownUntil, setRotateCooldownUntil] = useState<number | null>(null);
  const [rotateCooldownRemaining, setRotateCooldownRemaining] = useState(0);
  const [rotateConfirmOpen, setRotateConfirmOpen] = useState(false);
  const [swapSheetOpen, setSwapSheetOpen] = useState(false);
  const [swapConfirmOpen, setSwapConfirmOpen] = useState(false);
  const [swapLocationId, setSwapLocationId] = useState<number | typeof ANY>(ANY);
  const [swapCarrier, setSwapCarrier] = useState<Carrier | typeof ANY>(ANY);
  const [extendSheetOpen, setExtendSheetOpen] = useState(false);
  const [howToOpen, setHowToOpen] = useState(false);

  // Ticks once a second so the expiry progress bar animates smoothly. Called
  // unconditionally (before any early return) per the Rules-of-Hooks.
  const remainingMs = useCountdown(detailQuery.data?.expires_at);
  // Ticks the swap button's own countdown. Called here, beside the expiry one and before
  // any early return, for the same Rules-of-Hooks reason.
  const swapCooldownMs = useCountdown(detailQuery.data?.swap_available_at);

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

  // While rotating, useAccessDetail polls every 4s. Stop when the exit IP flips
  // (rotation confirmed) or after ~90s (a mobile reboot can be slow).
  const liveIp = detailQuery.data?.current_ip ?? null;
  useEffect(() => {
    if (!rotating) return;
    if (liveIp && liveIp !== ipBeforeRotate) {
      setRotating(false);
      showToast(`${strings.access.newIpPrefix} ${liveIp}`);
    }
  }, [rotating, liveIp, ipBeforeRotate, showToast]);
  useEffect(() => {
    if (!rotating) return;
    const timeout = setTimeout(() => setRotating(false), 90_000);
    return () => clearTimeout(timeout);
  }, [rotating]);

  async function handleRotate() {
    setRotateConfirmOpen(false);
    setIpBeforeRotate(detailQuery.data?.current_ip ?? null);
    try {
      await rotateIp.mutateAsync();
      setRotating(true);
      showToast(strings.access.rotatingHint);
    } catch (error) {
      if (isRetryAfterError(error)) {
        const seconds = getRetryAfterSeconds(error);
        setRotateCooldownUntil(Date.now() + seconds * 1000);
      }
    }
  }

  async function handleSwap() {
    setSwapConfirmOpen(false);
    try {
      await swapAccess.mutateAsync({
        location_id: swapLocationId === ANY ? undefined : swapLocationId,
        carrier: swapCarrier === ANY ? undefined : swapCarrier,
      });
      showToast(strings.access.swapDoneToast);
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : strings.errors.generic, "error");
    }
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
    try {
      await requestConfig.mutateAsync({ type });
      showToast(strings.access.configSentToast);
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : strings.errors.generic, "error");
    }
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
  const creds = access.credentials;
  const httpLogin = creds.http_login ?? creds.login;
  const httpPassword = creds.http_password ?? creds.password;
  // One button hands over everything the buyer pastes into their tooling: both proxies
  // in host:port:login:pass form and the rotation URL, blank line between them. A line
  // is omitted rather than emitted half-empty — a "socks5://host::" that cannot connect
  // is worse than no socks5 line at all.
  const httpLine =
    creds.host && creds.http_port
      ? `http://${creds.host}:${creds.http_port}:${httpLogin ?? ""}:${httpPassword ?? ""}`
      : null;
  const socksLine =
    creds.host && creds.socks5_port
      ? `socks5://${creds.host}:${creds.socks5_port}:${creds.socks5_login ?? ""}:${
          creds.socks5_password ?? ""
        }`
      : null;
  const combined = [httpLine, socksLine, creds.rotation_link].filter(Boolean).join("\n\n");

  // Expiry progress: width = remaining / total. The total duration is taken
  // from the catalog tariff matching this access's tariff_code (in minutes →
  // ms). Falls back to a 100% bar when the tariff can't be resolved.
  const totalMs =
    (catalogQuery.data?.tariffs.find((t) => t.code === access.tariff_code)?.duration_minutes ?? 0) * 60_000;
  const expiryPct = totalMs > 0 ? Math.max(0, Math.min(100, (remainingMs / totalMs) * 100)) : 100;
  // Revoked/expired/failed access is over. Everything below keys off this: a countdown
  // that keeps ticking under a "revoked" badge reads as "maybe it still works?", and the
  // Rotate/Extend buttons offer actions on something that no longer exists.
  const isEnded = ["revoked", "expired", "failed"].includes(access.status);

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
      <SectionLabel>{isEnded ? strings.access.endedLabel : strings.access.activeLabel}</SectionLabel>
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

        {/* current exit IP — lets the user verify Rotate IP actually changed it */}
        <div className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-border-2 bg-surface-2 px-3 py-2">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wide text-text-3">{strings.access.ipLabel}</div>
            <div className="flex items-center gap-1.5">
              <Num className="text-[14px] font-semibold text-text">{access.current_ip ?? "—"}</Num>
              {rotating ? <RefreshCw size={12} className="animate-spin text-accent" aria-hidden="true" /> : null}
            </div>
          </div>
          <button
            type="button"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] border border-border-2 text-text-3 transition-colors hover:bg-accent/[.08] hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
            aria-label="Copy IP"
            disabled={!access.current_ip}
            onClick={() => access.current_ip && copyIp(access.current_ip)}
          >
            {ipCopied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>

        {isEnded ? (
          <div className="mt-3.5 rounded-lg border border-border-2 bg-surface-2 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wide text-text-3">
              {strings.access.endedOnLabel}
            </div>
            <div className="text-[13px] font-medium text-text-2">
              {access.status === "revoked"
                ? strings.access.endedRevoked
                : access.status === "failed"
                  ? strings.access.endedFailed
                  : strings.access.endedExpired}
            </div>
          </div>
        ) : (
          <div className="mt-3.5">
            <div className="mb-1.5 flex items-baseline justify-between text-xs text-text-3">
              <span>{strings.common.expiresIn}</span>
              <CountdownBadge
                expiresAt={access.expires_at}
                variant="remaining"
                valueClassName="text-[13px]"
              />
            </div>
            <div className="h-[3px] overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-warning transition-[width] duration-500 ease-out"
                style={{ width: `${expiryPct}%` }}
              />
            </div>
          </div>
        )}

        {isEnded ? (
          <Button variant="primary" block className="mt-3.5" onClick={() => navigate("/catalog")}>
            {strings.access.endedBuyNew}
          </Button>
        ) : (
          <>
            <div className="mt-3.5 flex gap-2.5">
              <Button
                variant="primary"
                block
                disabled={rotateIp.isPending || rotating || rotateCooldownRemaining > 0}
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

            {/* Shown on every live access, not just the trial: the limit is one a day
                rather than a handful per plan. Disabled with the wait on it while it
                cools, because a button that only returns an error is worse than a
                button that says when it will work. */}
            <Button
              variant="ghost"
              block
              className="mt-2"
              disabled={swapCooldownMs > 0}
              onClick={() => setSwapSheetOpen(true)}
            >
              <ArrowLeftRight size={15} aria-hidden="true" />
              {swapCooldownMs > 0 ? (
                <>
                  {strings.access.swapNextIn}{" "}
                  <Num>{formatTimeLeft(Math.floor(swapCooldownMs / 1000))}</Num>
                </>
              ) : (
                strings.access.swap
              )}
            </Button>
          </>
        )}

        <p className={`mt-1.5 text-center text-[11px] leading-relaxed ${rotating ? "text-accent" : "text-text-3"}`}>
          {rotating ? strings.access.rotatingHint : strings.access.rotateNote}
        </p>
      </div>

      {/* ── auto-rotation (live access only — nothing to schedule on a dead one) ── */}
      {isEnded ? null : (
        <AutoRotatePanel publicId={publicId} current={access.auto_rotate_minutes} />
      )}

      {/* ── credentials: http ── */}
      <SectionLabel className="mt-[18px]">{strings.access.credentialsLabel}</SectionLabel>
      <div className="flex flex-col gap-1.5">
        <CopyField label={strings.access.hostLabel} value={creds.host ?? "—"} />
        <CopyField label={strings.access.httpPortLabel} value={creds.http_port?.toString() ?? "—"} />
        <CopyField label={strings.access.loginLabel} value={httpLogin ?? "—"} />
        <SecretRow label={strings.access.passLabel} value={httpPassword} />
      </div>

      {/* ── credentials: socks5 (own port and own pair — not the http one) ── */}
      <SectionLabel className="mt-[18px]">{strings.access.socks5CredentialsLabel}</SectionLabel>
      <div className="flex flex-col gap-1.5">
        <CopyField label={strings.access.hostLabel} value={creds.host ?? "—"} />
        <CopyField label={strings.access.socksPortLabel} value={creds.socks5_port?.toString() ?? "—"} />
        <CopyField label={strings.access.loginLabel} value={creds.socks5_login ?? "—"} />
        <SecretRow label={strings.access.passLabel} value={creds.socks5_password} />
      </div>

      {/* ── rotation link ── */}
      {creds.rotation_link ? (
        <>
          <SectionLabel className="mt-[18px]">{strings.access.rotationLinkSectionLabel}</SectionLabel>
          <CopyField label={strings.access.rotationLinkLabel} value={creds.rotation_link} />
          <p className="mt-1.5 px-1 text-[11px] leading-relaxed text-text-3">
            {strings.access.rotationLinkHint}
          </p>
        </>
      ) : null}

      {/* ── combined copy ── */}
      <div className="mt-3 flex items-start gap-2.5 rounded border border-border-2 bg-surface p-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-text-3">{strings.access.combinedLabel}</div>
          <Num className="block overflow-hidden whitespace-pre-line break-all text-[11px] leading-[1.6] text-text-2">
            {combined || "—"}
          </Num>
        </div>
        <button
          type="button"
          className="flex h-[38px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[8px] border border-border-2 bg-transparent px-3.5 text-xs font-medium text-accent transition-colors hover:bg-accent/[.08] hover:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
          disabled={!combined}
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
                  label={formatCityState(loc.city, loc.state_code)}
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
          {/* Same gate the catalogue uses, plus a price: the backend refuses to extend on
              a free or quote-only plan ("tariff not valid for extension"), so listing one
              here offered a button whose only outcome was an error. Reseller sat in this
              sheet at $0.00 for exactly that reason. */}
          {catalogQuery.data?.tariffs
            .filter((t) => t.code !== "trial" && t.kind === "auto" && t.auto_issue && t.price_usd > 0)
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

const AUTO_ROTATE_DEFAULT_MINUTES = 30;

/** Switch + interval for scheduled rotation. Its own component so the draft interval is
 *  local state that cannot desync from the saved one on the screen around it. */
function AutoRotatePanel({ publicId, current }: { publicId: string | undefined; current: number | null }) {
  const setAutoRotate = useSetAutoRotate(publicId);
  const { showToast } = useToast();
  const [draft, setDraft] = useState(String(current ?? AUTO_ROTATE_DEFAULT_MINUTES));

  // Follows the server after a save or a refetch, so the field never shows an interval
  // that is not the one actually running.
  useEffect(() => {
    if (current !== null) setDraft(String(current));
  }, [current]);

  const enabled = current !== null;
  const parsed = Number.parseInt(draft, 10);
  const valid = Number.isFinite(parsed) && parsed >= 1 && parsed <= 1440;
  const dirty = valid && parsed !== current;

  async function save(nextEnabled: boolean, minutes: number | null) {
    try {
      await setAutoRotate.mutateAsync({ enabled: nextEnabled, minutes });
      showToast(nextEnabled ? strings.access.autoRotateOnToast : strings.access.autoRotateOffToast);
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : strings.errors.generic, "error");
    }
  }

  return (
    <>
      <SectionLabel className="mt-[18px]">{strings.access.autoRotateLabel}</SectionLabel>
      <div className="rounded-xl border border-border bg-surface p-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13.5px] font-medium text-text">{strings.access.autoRotateLabel}</div>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-text-3">
              {strings.access.autoRotateHint}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label={strings.access.autoRotateLabel}
            disabled={setAutoRotate.isPending}
            onClick={() => save(!enabled, enabled ? null : (valid ? parsed : AUTO_ROTATE_DEFAULT_MINUTES))}
            className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors duration-200 disabled:opacity-40 ${
              enabled ? "border-accent bg-accent/[.9]" : "border-border-2 bg-surface-2"
            }`}
          >
            <span
              className={`absolute top-[3px] h-4 w-4 rounded-full bg-surface shadow transition-[left] duration-200 ease-out ${
                enabled ? "left-[25px]" : "left-[3px]"
              }`}
            />
          </button>
        </div>

        {enabled ? (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-[12.5px] text-text-2">{strings.access.autoRotateEvery}</span>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={1440}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="num h-9 w-20 rounded border border-border bg-surface-2 px-2.5 text-[13px] text-text outline-none focus-visible:border-accent"
            />
            <span className="text-[12.5px] text-text-2">{strings.access.autoRotateMinutesUnit}</span>
            <Button
              variant="default"
              className="ml-auto"
              disabled={!dirty || setAutoRotate.isPending}
              onClick={() => save(true, parsed)}
            >
              {strings.access.autoRotateApply}
            </Button>
          </div>
        ) : null}
        {enabled && !valid ? (
          <p className="mt-1.5 text-[11px] text-warning">{strings.access.autoRotateRange}</p>
        ) : null}
      </div>
    </>
  );
}

/** Masked value with its own reveal + copy. A component rather than two more pieces of
 *  screen state, because there are now two of these (http and socks5) and a shared
 *  `revealed` flag would uncover both passwords at once. */
function SecretRow({ label, value }: { label: string; value: string | null }) {
  const [revealed, setRevealed] = useState(false);
  const { copied, copy } = useCopyToClipboard();

  return (
    <div className="flex items-center gap-0 h-11 overflow-hidden rounded border border-border bg-surface">
      <span className="flex h-full w-[58px] shrink-0 items-center border-r border-border bg-surface-2 px-2.5 font-mono text-[10px] uppercase tracking-wide text-text-3">
        {label}
      </span>
      <span className="num flex-1 overflow-hidden text-ellipsis whitespace-nowrap px-2.5 text-[13px] text-text">
        {value ? (revealed ? value : maskSecret(value)) : "—"}
      </span>
      <button
        type="button"
        className="flex h-full shrink-0 items-center justify-center border-l border-border px-2.5 text-[11px] font-medium text-text-2 transition-colors hover:text-accent disabled:opacity-40"
        disabled={!value}
        onClick={() => setRevealed((v) => !v)}
      >
        {revealed ? strings.common.hide : strings.common.reveal}
      </button>
      <button
        type="button"
        className="flex h-full w-11 shrink-0 items-center justify-center border-l border-border text-text-3 transition-colors duration-150 ease-out hover:bg-accent/[.08] hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
        aria-label={`Copy ${label}`}
        disabled={!value}
        onClick={() => value && copy(value)}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
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
