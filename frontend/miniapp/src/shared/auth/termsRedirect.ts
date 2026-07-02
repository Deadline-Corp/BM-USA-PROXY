// Shared sessionStorage key so the Terms screen knows where to return to
// after acceptance, regardless of whether the redirect was triggered by a
// per-action guard (useRequireTos / useTermsGate) or by catching a 428 from
// any order-creation call directly.
const RETURN_TO_KEY = "bm_terms_return_to";

export function rememberReturnTo(path: string): void {
  sessionStorage.setItem(RETURN_TO_KEY, path);
}

export function consumeReturnTo(fallback = "/"): string {
  const saved = sessionStorage.getItem(RETURN_TO_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
  return saved ?? fallback;
}
