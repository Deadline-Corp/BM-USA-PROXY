import clsx from "clsx";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger";

const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-surface-2 border-border text-text-2",
  accent: "bg-accent-soft border-accent-line text-accent",
  success: "bg-success-soft border-success-line text-success",
  warning: "bg-warning-soft border-warning-line text-warning-text",
  danger: "bg-danger-soft border-danger-line text-danger",
};

const dotClasses: Record<BadgeTone, string> = {
  neutral: "bg-text-3",
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
};

// Single source of truth mapping every backend status string to a visual
// tone. Extend this map when a new status string shows up rather than
// hand-picking tones inline in a screen — keeps the palette consistent.
const STATUS_TONE_MAP: Record<string, BadgeTone> = {
  // generic
  active: "success",
  inactive: "neutral",
  pending: "warning",
  // clients
  banned: "danger",
  ok: "success",
  // accesses / connections
  online: "success",
  offline: "neutral",
  full: "warning",
  expired: "neutral",
  revoked: "danger",
  // orders
  paid: "success",
  failed: "danger",
  refunded: "warning",
  manual_review: "warning",
  processing: "accent",
  // requests
  new: "accent",
  in_progress: "warning",
  waiting: "warning",
  done: "success",
  // payouts / referrals
  approved: "success",
  rejected: "danger",
  // broadcasts / posts
  draft: "neutral",
  scheduled: "accent",
  sent: "success",
  published: "success",
};

export function toneForStatus(status: string): BadgeTone {
  return STATUS_TONE_MAP[status] ?? "neutral";
}

interface StatusBadgeProps {
  /** Either pass a known backend status string (auto-mapped to a tone) or
   * an explicit tone + custom label. */
  status?: string;
  tone?: BadgeTone;
  label?: string;
  className?: string;
}

function humanize(status: string): string {
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function StatusBadge({ status, tone, label, className }: StatusBadgeProps) {
  const resolvedTone = tone ?? (status ? toneForStatus(status) : "neutral");
  const resolvedLabel = label ?? (status ? humanize(status) : "");
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 h-[23px] px-[9px] rounded-full border text-[.72rem] font-semibold whitespace-nowrap",
        toneClasses[resolvedTone],
        className,
      )}
    >
      <span className={clsx("w-1.5 h-1.5 rounded-full flex-none", dotClasses[resolvedTone])} />
      {resolvedLabel}
    </span>
  );
}
