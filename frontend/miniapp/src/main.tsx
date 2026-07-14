import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./shared/components/ErrorBoundary";
import "./index.css";

// ── Telegram viewport ──────────────────────────────────────────────────────
// 100dvh is unreliable inside the Telegram webview (it can exceed the visible
// area), which pushes the bottom tab bar out of view. Expand the mini-app to
// full height on launch and expose Telegram's real stable viewport height as
// the --tg-vh CSS var so the app shell can size to it. Falls back to 100dvh
// outside Telegram (dev / bare browser).
interface TgWebApp {
  ready?: () => void;
  expand?: () => void;
  viewportStableHeight?: number;
  viewportHeight?: number;
  onEvent?: (event: string, cb: () => void) => void;
}

document.documentElement.style.setProperty("--tg-vh", "100dvh");
(function initTelegramViewport(): void {
  const wa = (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;
  if (!wa) return;
  try {
    wa.ready?.();
    wa.expand?.();
    const apply = () => {
      const h = wa.viewportStableHeight || wa.viewportHeight;
      if (h) document.documentElement.style.setProperty("--tg-vh", `${h}px`);
    };
    apply();
    wa.onEvent?.("viewportChanged", apply);
  } catch {
    /* ignore — keep the 100dvh fallback */
  }
})();

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
