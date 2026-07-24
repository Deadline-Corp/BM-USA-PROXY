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
  if (!path.startsWith("/")) return false;
  let decoded = path;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    // malformed escapes — judge the raw string only
  }
  return !/^\/[/\\]/.test(path) && !/^\/[/\\]/.test(decoded);
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
