import { useEffect, useState } from "react";

/** Trailing-edge debounce for a value that drives a query.
 *
 * Used where a keystroke is expensive on the server rather than merely chatty: the ledger
 * search matches a substring against transaction ids and addresses, which no index can
 * serve, so firing one scan per character is a real cost once the table has a year in it.
 */
export function useDebouncedValue<T>(value: T, delayMs = 350): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);

  return debounced;
}
