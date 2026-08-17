import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import {
  useAppSettings,
  useUpdateAppSettings,
  useUploadWelcomeImage,
  useWelcomeImage,
} from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
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
  invoice_ttl_minutes: "Invoice lifetime (minutes)",
  rotation_cooldown_sec: "IP rotation cooldown (seconds)",
  pool_low_watermark: "Pool low-stock alert (free slots)",
  pool_check_interval_minutes: "Pool check interval (minutes)",
  // Comma-separated destinations for operator alerts: client messages, reseller enquiries,
  // low stock, the nightly reconciliation. Adds to OPS_ALERT_CHAT_ID rather than replacing
  // it. @handles are resolved to ids server-side (see services/ops_alerts.py), so an
  // operator writes the name they actually know. The person still has to have pressed
  // Start on the bot — Telegram does not let a bot open a conversation.
  ops_alert_chats: "Operator alert chats — @handles or ids, comma-separated",
  bot_channel_url: "Channel link",
  bot_support_url: "Support link",
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
//
// `operator_refund_limit_usd` is listed as retired rather than forgotten: roles are gone,
// so the backend no longer accepts the key, and a leftover row in the settings table would
// otherwise render a field that 400s the moment anyone edits anything in this panel.
const RETIRED_KEYS = ["operator_refund_limit_usd", "operator_payout_limit_usd"];

// Written by the code, never by a person. `welcome_image_file_id` is Telegram's own id for
// the greeting photo, cached so /start resends it instead of re-uploading the bytes; the
// upload panel below clears it on every replace. Showing it as an editable text box put a
// value nobody can produce by hand next to settings that invite editing — and a wrong id
// there means the bot sends somebody else's photo, or fails to send one at all.
const INTERNAL_KEYS = ["welcome_image_file_id"];

const isManaged = (key: string) =>
  key.startsWith("notify_texts:") ||
  key === "tos" ||
  RETIRED_KEYS.includes(key) ||
  INTERNAL_KEYS.includes(key);

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

const WELCOME_IMAGE_ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const WELCOME_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

/** The bot's /start greeting photo — a coverage-map image, replaceable from here. Not part
 * of the free-form grid above: an image doesn't fit a text `<Input>`, and the backend
 * stores it in its own table rather than the JSONB settings bag (see
 * app/services/media.py).
 *
 * The preview is fetched as an authenticated blob rather than a plain `<img src>` — the
 * endpoint sits behind the same bearer-token auth as the rest of the admin API, which an
 * `<img>` tag has no way to send. `cacheBust` is threaded into the fetch (both the query
 * key and the request URL) and bumped after every successful upload, so the browser can't
 * paint the just-replaced image from a cached copy of "the same" URL.
 */
export function WelcomeImagePanel() {
  const toast = useToast();
  const [cacheBust, setCacheBust] = useState(() => Date.now());
  const { data: blob, isLoading, isError, refetch } = useWelcomeImage(cacheBust);
  const uploadMutation = useUploadWelcomeImage();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // One object URL alive at a time — each new blob revokes the last, so replacing the
  // image a dozen times in a session doesn't leak a dozen blob URLs.
  useEffect(() => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // so picking the same filename again still fires onChange
    if (!file) return;
    if (!WELCOME_IMAGE_ACCEPTED_TYPES.includes(file.type)) {
      toast.error(strings.settings.welcomeImageBadType);
      return;
    }
    if (file.size > WELCOME_IMAGE_MAX_BYTES) {
      toast.error(strings.settings.welcomeImageTooLarge);
      return;
    }
    try {
      await uploadMutation.mutateAsync(file);
      setCacheBust(Date.now());
      toast.success(strings.settings.welcomeImageUploaded);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Panel>
      <Panel.Head
        title={strings.settings.welcomeImage}
        subtitle={strings.settings.welcomeImageHint}
      />
      <Panel.Body>
        {isLoading ? (
          <Skeleton className="h-[180px] w-[320px]" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : (
          <div className="flex items-end gap-4 flex-wrap">
            {previewUrl && (
              <img
                src={previewUrl}
                alt={strings.settings.welcomeImage}
                className="w-[320px] max-w-full rounded-lg border border-border object-cover"
              />
            )}
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept={WELCOME_IMAGE_ACCEPTED_TYPES.join(",")}
                className="hidden"
                onChange={handleFileChange}
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                isLoading={uploadMutation.isPending}
              >
                {strings.settings.welcomeImageReplace}
              </Button>
            </div>
          </div>
        )}
      </Panel.Body>
    </Panel>
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
          isDirty && (
            <Button size="sm" variant="primary" onClick={handleSave} isLoading={updateMutation.isPending}>
              {strings.common.save}
            </Button>
          )
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
                <Input
                  key={key}
                  label={labelFor(key)}
                  value={String(value)}
                  size={1}
                  onChange={(e) => setDraft((prev) => ({ ...(prev ?? data), [key]: e.target.value }))}
                />
              ))}
            </div>
            {footnote && <p className="mt-4 text-[.78rem] text-text-3">{footnote}</p>}
          </>
        )}
      </Panel.Body>
    </Panel>
  );
}
