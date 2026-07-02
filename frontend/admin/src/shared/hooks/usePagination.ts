import { useState } from "react";

/** Local offset/limit pagination state for a single list screen. Kept
 * simple (no URL sync) — matches the scope requested in the task spec. */
export function usePagination(limit = 20) {
  const [offset, setOffset] = useState(0);
  return { limit, offset, setOffset, resetOffset: () => setOffset(0) };
}
