import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./shared/components/ErrorBoundary";
import "./index.css";
import { isTyping, shellHeight } from "./shared/lib/viewport";

// ── viewport height ────────────────────────────────────────────────────────
// `100dvh` is unreliable inside the Telegram webview — it can resolve to the largest
// viewport rather than the current one, which pushes the bottom tab bar out of sight. So
// the shell sizes to a --tg-vh set from JavaScript, and this expands the mini app to full
// height on launch so there is a full height to measure. What goes into the number, and
// why Telegram's own viewport figures are not in it, is in shared/lib/viewport.ts.
interface TgWebApp {
  ready?: () => void;
  expand?: () => void;
  viewportStableHeight?: number;
  viewportHeight?: number;
  onEvent?: (event: string, cb: () => void) => void;
}

document.documentElement.style.setProperty("--tg-vh", "100dvh");
(function initViewportHeight(): void {
  // The rule lives in shared/lib/viewport.ts. Telegram's own viewport numbers are
  // deliberately NOT part of it any more — see that file. They are still worth listening
  // for, because a `viewportChanged` is a reliable hint that `innerHeight` just moved.
  const wa = (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;
  const apply = () => {
    const h = shellHeight({
      inner: window.innerHeight,
      visual: window.visualViewport?.height,
      typing: isTyping(document.activeElement),
    });
    // `null` is "no usable source", and it has to WRITE the fallback rather than return:
    // returning would leave whatever pixel value was set a moment ago, which is the same
    // stuck-short state this whole function exists to prevent, arrived at from the other
    // direction.
    document.documentElement.style.setProperty("--tg-vh", h === null ? "100dvh" : `${h}px`);
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
  // The shell can only shrink while a field has focus, so losing it has to re-measure —
  // this is what puts the height back on Android, where the keyboard closing does not
  // reliably announce itself through `visualViewport` at all. Deferred a tick: `focusout`
  // fires before the `focusin` of whatever was tapped next, and reading the focus in
  // between would expand the shell for one frame on every hop from field to field.
  document.addEventListener("focusin", apply);
  document.addEventListener("focusout", () => window.setTimeout(apply, 0));
  // Android resizes the window itself rather than only the visual viewport, and a rotation
  // changes everything. Neither used to be listened for, so a height measured before them
  // simply stayed.
  window.addEventListener("resize", apply);
  window.addEventListener("orientationchange", apply);
  // Coming back to a backgrounded webview: Telegram may have re-laid it out meanwhile.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) apply();
  });
  apply();

  // A readout of every number this decision is made from, for when it is wrong on a phone
  // nobody here is holding. Off unless the URL says `?vp=1`, so it costs a substring test.
  // Written because the first fix for the Android tab bar was a guess about which source
  // was lying, and it was the wrong guess.
  if (window.location.search.includes("vp=1")) {
    const box = document.createElement("div");
    box.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#000c;color:#0f0;" +
      "font:11px/1.4 monospace;padding:6px 8px;white-space:pre;pointer-events:none";
    document.body.appendChild(box);
    const draw = () => {
      const vv = window.visualViewport;
      box.textContent = [
        `--tg-vh ${getComputedStyle(document.documentElement).getPropertyValue("--tg-vh").trim()}`,
        `inner   ${window.innerHeight}   outer ${window.outerHeight}`,
        `visual  ${vv ? Math.round(vv.height) : "-"}  offTop ${vv ? Math.round(vv.offsetTop) : "-"}  scale ${vv ? vv.scale : "-"}`,
        `tg      stable ${wa?.viewportStableHeight ?? "-"}  vp ${wa?.viewportHeight ?? "-"}`,
        `typing  ${isTyping(document.activeElement)}   dpr ${window.devicePixelRatio}`,
      ].join(String.fromCharCode(10));
    };
    window.setInterval(draw, 250);
    draw();
  }

  // Shrinking the shell is only half the job. The area left over is shorter, so a field
  // that sat near the bottom is now below it — still on the page, simply out of view, with
  // nothing to scroll it back. On Android the webview does this itself, which is why it
  // was only ever reported from iPhones: the Terms email field first, then the
  // auto-rotation interval, and each time the person is typing into something they cannot
  // see. Every scroller in this app is an inner one, so the browser's own "scroll the
  // focused thing into view" never fires.
  const showFocused = () => {
    const el = document.activeElement;
    if (!(el instanceof HTMLElement)) return;
    if (!el.matches("input, textarea, select, [contenteditable]")) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  // Twice, at two delays, because the keyboard animates: iOS reports the new viewport
  // partway through, so a single early scroll lands on a height that is about to change.
  const showFocusedSoon = () => {
    window.setTimeout(showFocused, 120);
    window.setTimeout(showFocused, 400);
  };
  // focusin, not focus: it bubbles, so one listener covers every field in the app rather
  // than each screen having to remember.
  document.addEventListener("focusin", showFocusedSoon);
  // …and again when the keyboard itself resizes the viewport, which on iOS can happen
  // well after the field was focused — switching between a text and a number pad, or the
  // predictive-text bar appearing.
  window.visualViewport?.addEventListener("resize", showFocused);
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
