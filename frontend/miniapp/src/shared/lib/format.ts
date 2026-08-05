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

/** Formats a duration in seconds as H:MM:SS (or MM:SS under an hour). */
export function formatDuration(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = clamped % 60;
  if (hours > 0) {
    return `${hours}:${pad2(minutes)}:${pad2(seconds)}`;
  }
  return `${minutes}:${pad2(seconds)}`;
}

/** Milliseconds remaining until an ISO timestamp; negative once passed. */
export function msUntil(iso: string): number {
  return new Date(iso).getTime() - Date.now();
}

export function maskSecret(value: string, visibleTail = 4): string {
  if (value.length <= visibleTail) return "•".repeat(value.length);
  return `${"•".repeat(Math.max(4, value.length - visibleTail))}${value.slice(-visibleTail)}`;
}
