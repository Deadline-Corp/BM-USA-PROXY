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
(function initViewportHeight(): void {
  // Two sources, and the smaller one wins, because neither is right alone:
  //
  // * Telegram's `viewportStableHeight` is stable BY DEFINITION — it deliberately
  //   ignores transient changes, and the on-screen keyboard is exactly that. Size
  //   to it alone and the app keeps its full height while the keyboard covers the
  //   bottom third of it: on the Terms screen that hid the email field the person
  //   had just tapped, and the Accept button below it.
  // * `visualViewport.height` is precisely the part the keyboard is not covering,
  //   but it is absent in older webviews.
  //
  // The smaller of the two is what can actually be painted on right now.
  const wa = (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;
  const apply = () => {
    const heights = [
      wa?.viewportStableHeight || wa?.viewportHeight,
      window.visualViewport?.height,
    ].filter((h): h is number => typeof h === "number" && h > 0);
    if (heights.length === 0) return; // no source — keep the 100dvh fallback
    document.documentElement.style.setProperty("--tg-vh", `${Math.min(...heights)}px`);
    // iOS also scrolls the LAYOUT viewport up when the keyboard opens, which slides
    // the app's own header off the top even though the shell is exactly as tall as
    // what is visible. Nothing here scrolls the window — every scroller in the app
    // is an inner one — so putting it back at zero is always the right answer.
    if (window.scrollY !== 0) window.scrollTo(0, 0);
  };

  try {
    wa?.ready?.();
    wa?.expand?.();
    wa?.onEvent?.("viewportChanged", apply);
  } catch {
    /* ignore — the visualViewport half below still works */
  }
  // iOS slides the layout viewport out from under the keyboard as well as
  // resizing it, so both events matter.
  window.visualViewport?.addEventListener("resize", apply);
  window.visualViewport?.addEventListener("scroll", apply);
  apply();
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
