/**
 * Where the mini app is running, and how to hand a payment to a wallet from there.
 *
 * An `ethereum:` / `bitcoin:` / `solana:` URL is resolved by the OS scheme registry. A
 * normal mobile browser consults it; a WebView only does if its host app forwards the
 * scheme, and Telegram's Android WebView does not. Navigating to one there does not fail
 * quietly — it aborts the page with ERR_UNKNOWN_URL_SCHEME and takes the whole mini app
 * down mid-payment (observed on Android, 2026-08-07, paying ETH on Sepolia).
 *
 * The way through is not to give up the button but to stop navigating the WebView:
 * `openLink` asks the Telegram client to open an https URL in the *real* browser, which
 * does consult the registry. The backend serves `/pay/{order}`, which redirects into the
 * scheme, so the buyer still lands on the wallet chooser with the transaction filled in.
 */
interface TgWebApp {
  platform?: string;
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
}

function webApp(): TgWebApp | undefined {
  return (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;
}

/** Telegram's own value ("android" | "ios" | "tdesktop" | "macos" | "weba" | …). */
export function telegramPlatform(): string {
  return webApp()?.platform ?? "unknown";
}

/** Inside a real Telegram client, as opposed to a plain browser tab (dev, or a shared link). */
export function isInsideTelegram(): boolean {
  return telegramPlatform() !== "unknown";
}

function isMobilePlatform(): boolean {
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

/**
 * What tapping "Open in wallet" should actually load, or null when it should not be shown.
 *
 * Two different targets for the same button. Inside Telegram it must be the https
 * hand-off, because the WebView cannot survive the scheme; outside it, the scheme itself
 * is both fine and one hop shorter. Desktop gets nothing either way — no desktop OS
 * claims `ethereum:`, MetaMask there is a browser extension that never sees it.
 */
export function walletLinkTarget(invoice: {
  pay_uri?: string | null;
  pay_open_url?: string | null;
}): string | null {
  if (!isMobilePlatform()) return null;
  if (isInsideTelegram()) {
    // Needs a client new enough to have openLink (Bot API 6.1). Without it there is no
    // way out of the WebView, and navigating directly is the crash we are avoiding.
    return webApp()?.openLink ? invoice.pay_open_url ?? null : null;
  }
  return isWalletDeepLink(invoice.pay_uri) ? invoice.pay_uri ?? null : null;
}

/** Open a target from {@link walletLinkTarget} by whichever route is safe here. */
export function openWalletLink(target: string): void {
  const wa = webApp();
  if (isInsideTelegram() && wa?.openLink) {
    wa.openLink(target); // https → external browser → OS wallet chooser
    return;
  }
  window.location.href = target; // plain browser: the scheme registry handles it
}
