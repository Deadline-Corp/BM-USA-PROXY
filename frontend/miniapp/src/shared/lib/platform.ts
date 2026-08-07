/**
 * Where the mini app is running, and whether a wallet deep link can survive there.
 *
 * Only used to decide whether to offer the wallet button. A `ethereum:` / `bitcoin:` /
 * `solana:` URL is resolved by the OS scheme registry, which a normal mobile browser
 * consults — but a WebView only does so if its host app forwards the scheme, and
 * Telegram's Android WebView does not. Navigating to one there does not fail quietly:
 * it aborts the page with ERR_UNKNOWN_URL_SCHEME and takes the whole mini app down,
 * mid-payment (observed on Android, 2026-08-07, paying ETH on Sepolia).
 */
interface TgPlatform {
  platform?: string;
}

/** Telegram's own value ("android" | "ios" | "tdesktop" | "macos" | "weba" | …). */
export function telegramPlatform(): string {
  const wa = (window as unknown as { Telegram?: { WebApp?: TgPlatform } }).Telegram?.WebApp;
  return wa?.platform ?? "unknown";
}

/** Inside a real Telegram client, as opposed to a plain browser tab (dev, or a shared link). */
export function isInsideTelegram(): boolean {
  return telegramPlatform() !== "unknown";
}

// Deliberately not exported. "Is this a phone" is the question that produced the crash —
// callers wanting to offer a wallet link must ask `canOpenWalletLink` instead.
function isMobilePlatform(): boolean {
  const p = telegramPlatform();
  if (p === "android" || p === "ios") return true;
  // Telegram reports "unknown" outside its client (dev, bare browser) — fall back to the
  // user agent so the button is still testable rather than invisible.
  if (p === "unknown") return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  return false;
}

/**
 * Whether tapping a wallet deep link can do anything other than harm.
 *
 * Mobile is necessary but not sufficient: the link also has to be opened somewhere that
 * hands unknown schemes to the OS. Telegram's WebView does not, so inside the Telegram
 * client the button is withheld on every platform — including iOS, which may well cope,
 * because the cost of being wrong is the buyer's app dying on the payment screen while
 * the copy-address and copy-amount rows already offer a working way through.
 */
export function canOpenWalletLink(): boolean {
  return isMobilePlatform() && !isInsideTelegram();
}

/**
 * True when the payload is a wallet deep link rather than a bare address.
 *
 * The backend hands back a URI where the chain has a standard (EIP-681, BIP-21, Solana
 * Pay) and the plain address where it does not — Tron, today. Only the former can open
 * anything.
 */
export function isWalletDeepLink(payload: string | null | undefined): boolean {
  return Boolean(payload && /^[a-z][a-z0-9+.-]*:/i.test(payload));
}
