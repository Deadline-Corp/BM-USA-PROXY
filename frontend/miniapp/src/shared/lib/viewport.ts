/** How tall the app shell should be, given what each viewport source is saying.
 *
 * Pure, and separate from `main.tsx`, because the rule is the whole of two reported bugs.
 *
 * `window.innerHeight` is the base, and it is the only source that is in CSS pixels of this
 * document. Telegram's `viewportStableHeight` used to be the base, and it is what parked
 * the bottom tab bar in the middle of an Android screen with dead space beneath it: it is a
 * number Telegram computes in its own units for its own window, nothing here can check it,
 * and on that phone it came back at roughly 60% of the webview. The shell was then 60% of
 * the screen and there was no way back from it. `innerHeight` cannot be wrong that way — it
 * is the box the CSS is laid out in, asked directly.
 *
 * The keyboard is the one reason to use less than all of it, and a keyboard is only up
 * while something is being typed into. So `visual` counts when, and only when, a text field
 * has focus. That gate matters because on Android the event saying the visual viewport grew
 * back does not reliably arrive, and a transient value written into persistent layout state
 * becomes permanent the moment one event goes missing.
 */
export interface ViewportSources {
  /** `window.innerHeight` — the layout viewport, in this document's own CSS pixels. */
  inner?: number | null;
  /** `window.visualViewport.height` — what the keyboard is not covering. */
  visual?: number | null;
  /** A text-entry element has focus, so the keyboard is up or coming up. */
  typing: boolean;
}

export function shellHeight({ inner, visual, typing }: ViewportSources): number | null {
  const base = typeof inner === "number" && inner > 0 ? inner : null;
  // Nothing usable — the caller writes its 100dvh fallback. It must WRITE it rather than
  // skip the write: leaving the pixel value from a moment ago is the same stuck-short shell
  // reached from the other side.
  if (base === null) return null;
  if (typing && typeof visual === "number" && visual > 0) return Math.min(base, visual);
  return base;
}

const TYPING_SELECTOR = "input, textarea, select, [contenteditable]";

/** Whether the keyboard is up, asked in the only way that is reliable on both platforms.
 *
 * Not measured from the viewport — that is the thing we do not trust here. `focusin` and
 * `focusout` fire on every platform, and a keyboard with nothing focused is not a state
 * either of them produces.
 */
export function isTyping(active: Element | null): boolean {
  return active instanceof HTMLElement && active.matches(TYPING_SELECTOR);
}
