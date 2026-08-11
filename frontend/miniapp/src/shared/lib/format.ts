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

/**
 * Largest unit first. Single letters, no space before them: this string is a countdown
 * that reaches five units, so every character it does not spend is width it keeps.
 * "mo" is the exception — month and minute cannot both be "m".
 */
const UNITS: ReadonlyArray<{ label: string; size: number }> = [
  { label: "mo", size: MONTH },
  { label: "w", size: WEEK },
  { label: "d", size: DAY },
  { label: "h", size: HOUR },
  { label: "m", size: MINUTE },
  { label: "s", size: 1 },
];

/**
 * A stopwatch — for a short window where the seconds are the thing being watched.
 *
 * Used by the payment countdown, whose whole span is the invoice's hour. `MM:SS` is the
 * shape people already read as "time running out", and it is what belongs beside "waiting
 * for your payment".
 */
export function formatDuration(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(clamped / HOUR);
  const minutes = Math.floor((clamped % HOUR) / MINUTE);
  const seconds = clamped % MINUTE;
  if (hours > 0) return `${hours}:${pad2(minutes)}:${pad2(seconds)}`;
  return `${minutes}:${pad2(seconds)}`;
}

/**
 * How much of an access is left, counting down to the second.
 *
 * `719:55:31` for a month was unreadable, but so is stopping at the two largest units: a
 * countdown that does not move is not a countdown. This runs from the largest unit that
 * has anything in it all the way to seconds, so the row is always alive — `4w 1d 23h 55m
 * 31s` at the start of a month, `45m 12s` near the end.
 *
 * Leading zeros are skipped, so twenty hours left reads `20h 15m 3s` rather than
 * `0mo 0w 0d 20h …`. Zeros *inside* the run are kept: dropping them would shorten the
 * string mid-tick and make the numbers jump sideways every time a unit emptied.
 */
export function formatTimeLeft(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const parts: string[] = [];
  let rest = clamped;
  for (const { label, size } of UNITS) {
    const value = Math.floor(rest / size);
    if (value === 0 && parts.length === 0 && size > 1) continue; // nothing started yet
    parts.push(`${value}${label}`);
    rest -= value * size;
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
