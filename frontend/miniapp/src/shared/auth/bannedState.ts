import { useSyncExternalStore } from "react";

// A tiny module-level flag flipped when any query/mutation hits the backend's
// "account banned" 403 (wired in App.tsx's QueryCache/MutationCache onError).
// AuthGate reads it via useBanned() and renders the banned screen — this way the
// ban is caught from ANY request without a bootstrap probe or per-screen handling.
let banned = false;
const listeners = new Set<() => void>();

export function markBanned(): void {
  if (banned) return;
  banned = true;
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useBanned(): boolean {
  return useSyncExternalStore(subscribe, () => banned, () => banned);
}
