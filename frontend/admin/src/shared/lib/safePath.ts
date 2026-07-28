/**
 * Internal app path only. Must start with "/", must NOT be protocol-relative
 * ("//evil.com" / "/\evil.com" / "/%5Cevil.com"), and must stay same-origin when
 * resolved. Used to sanitise a "return to where you came from" target that ultimately
 * originates from the address bar, so it must not become an open redirect.
 *
 * Reject control chars outright (a raw TAB/LF/CR inside "/\t/evil.com" is dropped by the
 * URL parser and would otherwise cross origin), then let the browser's own URL parser
 * decide the origin instead of re-implementing URL parsing with a regex.
 */
export function isSafeInternalPath(path: string): boolean {
  if (typeof path !== "string" || !path.startsWith("/")) return false;
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
