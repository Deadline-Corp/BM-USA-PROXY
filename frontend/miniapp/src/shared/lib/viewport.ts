/** How tall the app shell should be, given what each viewport source is saying.
 *
 * Pure, and separate from `main.tsx`, because the rule is the whole bug. Sizing the shell
 * to `min(telegramStable, visualViewport)` unconditionally is what parked the bottom tab
 * bar in the middle of an Android screen with dead space under it: `visualViewport.height`
 * shrinks for the keyboard, and on Android the event that says it grew back does not always
 * arrive. The last small value then stuck, and nothing on screen could put it right —
 * the app was simply short for the rest of the session.
 *
 * The keyboard is the only reason the shell may shrink, and a keyboard is only up while
 * something is being typed into. So `visual` counts when, and only when, a text field has
 * focus. Lose the focus and the shell is Telegram's stable height again, whatever the
 * viewport events did or did not do.
 */
export interface ViewportSources {
  /** Telegram's `viewportStableHeight || viewportHeight`. Absent outside Telegram. */
  stable?: number | null;
  /** `window.visualViewport.height`. Absent in older webviews. */
  visual?: number | null;
  /** A text-entry element has focus, so the keyboard is up or coming up. */
  typing: boolean;
}

export function shellHeight({ stable, visual, typing }: ViewportSources): number | null {
  const heights: number[] = [];
  if (typeof stable === "number" && stable > 0) heights.push(stable);
  // Only while typing. Outside that, this number carries no information the stable height
  // does not already have, and it carries the risk of being stale.
  if (typing && typeof visual === "number" && visual > 0) heights.push(visual);
  // Nothing usable. `null` means "use 100dvh" and the caller must WRITE that, not skip the
  // write: leaving the pixel value from a moment ago is the same stuck-short shell, reached
  // from the other side.
  if (heights.length === 0) return null;
  return Math.min(...heights);
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
