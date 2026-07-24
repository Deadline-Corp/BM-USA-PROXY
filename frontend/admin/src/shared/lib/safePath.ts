/**
 * Internal app path only. Must start with "/" and must NOT be protocol-relative
 * ("//evil.com") or backslash-smuggled ("/\evil.com", "/%5Cevil.com") — routers
 * can treat those as absolute URLs, which turns a "return to the page you asked
 * for" redirect into an open redirect when the target came from the address bar.
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
