import { useEffect, useState } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import { useAppSettings, useUpdateAppSettings } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { RequireRole } from "@/shared/auth/RequireRole";
import type { AppSettings } from "@/shared/api/types";

/** Names for the keys we know about. Everything else falls back to the key with its
 * underscores knocked out, which is what keeps this panel useful when the backend grows a
 * setting without a frontend deploy — the point of the free-form bag below.
 *
 * The referral three are named after the labels the Referrals screen used to show them
 * under, because that screen no longer edits them: settings live in one place now, and a
 * setting called "referral pct" in one and "Commission %" in another is how two screens
 * end up disagreeing about which is authoritative.
 */
const SETTING_LABELS: Record<string, string> = {
  referral_pct: strings.referrals.commissionPct,
  referral_min_payout_usd: strings.referrals.minPayoutUsd,
  referral_hold_days: strings.referrals.holdDays,
  operator_refund_limit_usd: "Operator refund limit (USD)",
  invoice_ttl_minutes: "Invoice lifetime (minutes)",
  rotation_cooldown_sec: "IP rotation cooldown (seconds)",
  pool_low_watermark: "Pool low-stock alert (free slots)",
};

const labelFor = (key: string) => SETTING_LABELS[key] ?? key.replace(/_/g, " ");

/** The affiliate programme's three dials, in the order the Referrals screen used to show
 * them — commission first, since that is the one anybody actually comes here to change.
 * They get their own panel: a commission percentage sitting between "invoice lifetime"
 * and "pool low-stock alert" in one long grid is findable only by someone who already
 * knows it is there. */
const REFERRAL_KEYS = ["referral_pct", "referral_min_payout_usd", "referral_hold_days"];

// Structured settings (Terms, notification texts) have their own dedicated editors;
// the generic key/value grid only shows scalar keys, so object values never render
// as "[object Object]" and the two editors never fight over the same key.
const isManaged = (key: string) => key.startsWith("notify_texts:") || key === "tos";

/** Everything except the referral keys — the catch-all half of the bag. */
export function AppSettingsPanel() {
  return (
    <SettingsGroupPanel
      title={strings.settings.appSettings}
      select={(key) => !REFERRAL_KEYS.includes(key)}
      footnote="Terms of Service and notification message texts are edited on their own screens — see the Terms of service panel below and the Notifications page."
    />
  );
}

/** The referral trio, under the name the Referrals screen gave them. */
export function ReferralSettingsPanel() {
  return (
    <SettingsGroupPanel
      title={strings.referrals.settings}
      select={(key) => REFERRAL_KEYS.includes(key)}
      order={REFERRAL_KEYS}
    />
  );
}

/** App settings is a free-form key/value bag per the spec (`GET/PATCH
 * /settings` with no fixed schema given). We render every key as a text
 * input — good enough for an ops console where the shape is whatever the
 * backend currently exposes, and it degrades gracefully as keys are
 * added/removed server-side without a frontend deploy.
 *
 * Grouping is a `select` over the same bag rather than separate requests: the panels
 * partition the keyspace, and each saves only the keys it shows, so two drafts over one
 * query can never overwrite each other's values.
 */
function SettingsGroupPanel({
  title,
  select,
  order,
  footnote,
}: {
  title: string;
  select: (key: string) => boolean;
  /** Explicit key order; without it the backend's own order wins. */
  order?: string[];
  footnote?: string;
}) {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useAppSettings();
  const updateMutation = useUpdateAppSettings();
  const [draft, setDraft] = useState<AppSettings | null>(null);

  useEffect(() => {
    if (data && !draft) setDraft(data);
  }, [data, draft]);

  const visibleEntries = Object.entries(draft ?? data ?? {}).filter(
    ([key, value]) => !isManaged(key) && select(key) && (value === null || typeof value !== "object"),
  );
  if (order) visibleEntries.sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));

  // Dirty against this panel's own keys only — otherwise editing one panel lights up the
  // Save button on the other, and pressing it there would look like it saved your change.
  const isDirty =
    data !== undefined &&
    visibleEntries.some(([key, value]) => value !== (data as Record<string, unknown>)[key]);

  async function handleSave() {
    if (!draft || !data) return;
    // Send ONLY the scalar keys that actually changed — the bulk PATCH /settings
    // endpoint rejects keys outside its whitelist (tos / notify_texts have their own).
    const changed: Record<string, unknown> = {};
    for (const [key, value] of visibleEntries) {
      if (value !== (data as Record<string, unknown>)[key]) changed[key] = value;
    }
    try {
      await updateMutation.mutateAsync(changed as Partial<AppSettings>);
      toast.success("Settings saved");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Panel>
      <Panel.Head
        title={title}
        actions={
          <RequireRole role="owner">
            {isDirty && (
              <Button size="sm" variant="primary" onClick={handleSave} isLoading={updateMutation.isPending}>
                {strings.common.save}
              </Button>
            )}
          </RequireRole>
        }
      />
      <Panel.Body>
        {isLoading ? (
          <Skeleton className="h-24" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : visibleEntries.length === 0 ? (
          <EmptyState title="No editable settings" hint="Nothing in this group is exposed by the backend." />
        ) : (
          <>
            {/* Every field is exactly as wide as the longest label in the panel — these
                values are "60", "10", "23", and a box stretched across half the screen to
                hold two digits reads as a text area you are meant to write prose in.
                Two pieces make that work, and both look removable if you don't know why
                they are there:
                  · w-fit + equal 1fr tracks — inside a shrink-to-fit container, equal
                    tracks all resolve to the widest item, so the longest label sets the
                    width for the whole panel with no hardcoded number to go stale.
                  · size={1} — an input's own intrinsic width is 20 characters, which wins
                    over any label shorter than ~180px and would quietly re-inflate the
                    referral panel (measured: 150px → 179px). */}
            <div className="grid grid-cols-3 gap-x-6 gap-y-4 w-fit max-[820px]:grid-cols-2 max-[560px]:grid-cols-1">
              {visibleEntries.map(([key, value]) => (
                <RequireRole
                  key={key}
                  role="owner"
                  fallback={
                    <Input label={labelFor(key)} value={String(value)} size={1} disabled />
                  }
                >
                  <Input
                    label={labelFor(key)}
                    value={String(value)}
                    size={1}
                    onChange={(e) => setDraft((prev) => ({ ...(prev ?? data), [key]: e.target.value }))}
                  />
                </RequireRole>
              ))}
            </div>
            {footnote && <p className="mt-4 text-[.78rem] text-text-3">{footnote}</p>}
          </>
        )}
      </Panel.Body>
    </Panel>
  );
}
