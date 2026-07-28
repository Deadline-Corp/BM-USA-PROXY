// Shared sessionStorage key so the Terms screen knows where to return to
// after acceptance, regardless of whether the redirect was triggered by a
// per-action guard (useRequireTos / useTermsGate) or by catching a 428 from
// any order-creation call directly.
const RETURN_TO_KEY = "bm_terms_return_to";

/**
 * Internal app path only. Must start with "/" and must NOT be protocol-relative
 * ("//evil.com") or backslash-smuggled ("/\evil.com", "/%5Cevil.com") — routers
 * can treat those as absolute URLs, which turns "return to where you were" into
 * an open redirect, since the remembered path comes from the address bar.
 */
export function isSafeInternalPath(path: string): boolean {
  if (typeof path !== "string" || !path.startsWith("/")) return false;
  // Reject control chars (a raw TAB/LF/CR inside "/\t/evil.com" is dropped by the URL
  // parser and would otherwise cross origin), then let the browser's URL parser decide.
  for (let i = 0; i < path.length; i++) {
    const code = path.charCodeAt(i);
    if (code < 0x20 || code === 0x7f) return false;
  }
  if (/^\/[/\\]/.test(path)) return false;
  try {
    const origin = window.location.origin;
    return new URL(path, origin).origin === origin;
  } catch {
    return false;
  }
}

export function rememberReturnTo(path: string): void {
  if (!isSafeInternalPath(path)) return;
  sessionStorage.setItem(RETURN_TO_KEY, path);
}

export function consumeReturnTo(fallback = "/"): string {
  const saved = sessionStorage.getItem(RETURN_TO_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
  return saved && isSafeInternalPath(saved) ? saved : fallback;
}
