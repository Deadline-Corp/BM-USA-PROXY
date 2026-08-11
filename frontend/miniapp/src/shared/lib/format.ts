export function formatUsd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/**
 * Trim a quoted crypto amount for display without touching its value.
 *
 * The API sends the ledger's full NUMERIC(38,18) precision as a string, so a 6-decimal
 * quote arrives as "30.603405000000". Those zeros are noise on a screen whose whole job is
 * "send exactly this", and they invite the buyer to wonder whether they matter. String
 * maths only — parseFloat would defeat the point of sending a string in the first place.
 */
export function formatCryptoAmount(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  if (!/^-?\d+(\.\d+)?$/.test(value)) return value; // unexpected shape — show as-is
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-" ? "0" : trimmed;
}

export function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
/** A month is 30 days here because that is what the Monthly tariff is: 43 200 minutes. */
const MONTH = 30 * DAY;

/** Largest unit first. Labels are English because the mini-app ships English only. */
const UNITS: ReadonlyArray<{ label: string; size: number }> = [
  { label: "mo", size: MONTH },
  { label: "wk", size: WEEK },
  { label: "d", size: DAY },
  { label: "h", size: HOUR },
  { label: "m", size: MINUTE },
  { label: "s", size: 1 },
];

/**
 * How much time is left, in units a person can act on.
 *
 * Under an hour this stays a stopwatch (`MM:SS`). That covers the payment window and the
 * final hour of an access — the two moments where the seconds are the thing being watched,
 * and where a ticking clock is the familiar shape.
 *
 * Above an hour it switches to named units, because the stopwatch stops meaning anything:
 * a month of access read `719:55:31`, and nobody converts that to "about four weeks" while
 * deciding whether to extend.
 *
 * Two units, never more. The third is always smaller than the error a person cares about —
 * "4 wk 1 d 3 h 12 m 5 s" is not more informative than "4 wk 1 d", it is just harder to
 * read at a glance. Zero-valued units are skipped, so 32 days reads "1 mo 2 d", not
 * "1 mo 0 wk".
 */
export function formatDuration(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));

  if (clamped < HOUR) {
    return `${Math.floor(clamped / MINUTE)}:${pad2(clamped % MINUTE)}`;
  }

  const parts: string[] = [];
  let rest = clamped;
  for (const { label, size } of UNITS) {
    const value = Math.floor(rest / size);
    if (value > 0) {
      parts.push(`${value} ${label}`);
      rest -= value * size;
    }
    if (parts.length === 2) break;
  }
  return parts.join(" ");
}

/** Milliseconds remaining until an ISO timestamp; negative once passed. */
export function msUntil(iso: string): number {
  return new Date(iso).getTime() - Date.now();
}

export function maskSecret(value: string, visibleTail = 4): string {
  if (value.length <= visibleTail) return "•".repeat(value.length);
  return `${"•".repeat(Math.max(4, value.length - visibleTail))}${value.slice(-visibleTail)}`;
}
