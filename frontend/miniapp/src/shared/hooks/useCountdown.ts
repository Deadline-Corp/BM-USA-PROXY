import { useEffect, useState } from "react";
import { msUntil } from "../lib/format";

/** Ticks once a second, returning milliseconds remaining until `iso` (clamped at 0). */
export function useCountdown(iso: string | null | undefined): number {
  const [remainingMs, setRemainingMs] = useState<number>(() => (iso ? Math.max(0, msUntil(iso)) : 0));

  useEffect(() => {
    if (!iso) {
      setRemainingMs(0);
      return;
    }
    setRemainingMs(Math.max(0, msUntil(iso)));
    const interval = setInterval(() => {
      setRemainingMs(Math.max(0, msUntil(iso)));
    }, 1000);
    return () => clearInterval(interval);
  }, [iso]);

  return remainingMs;
}
