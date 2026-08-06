/**
 * Which device the mini app is running on.
 *
 * Only used to decide whether a wallet deep link is worth offering. Those links are
 * handled by the OS scheme registry, and on desktop nothing registers `ethereum:` —
 * MetaMask lives inside the browser and never sees it. A button that silently does
 * nothing is worse than no button, so the wallet action is mobile-only.
 */
interface TgPlatform {
  platform?: string;
}

/** Telegram's own value ("android" | "ios" | "tdesktop" | "macos" | "weba" | …). */
export function telegramPlatform(): string {
  const wa = (window as unknown as { Telegram?: { WebApp?: TgPlatform } }).Telegram?.WebApp;
  return wa?.platform ?? "unknown";
}

export function isMobilePlatform(): boolean {
  const p = telegramPlatform();
  if (p === "android" || p === "ios") return true;
  // Telegram reports "unknown" outside its client (dev, bare browser) — fall back to the
  // user agent so the button is still testable rather than invisible.
  if (p === "unknown") return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  return false;
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
