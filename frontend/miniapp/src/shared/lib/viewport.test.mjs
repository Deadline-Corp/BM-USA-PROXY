/**
 * The shell-height rule. Run with `node --test src/shared/lib/viewport.test.mjs`.
 *
 * A plain node test rather than a framework: this file exists because of one reported bug
 * on one Android phone, and the thing worth pinning down is a five-line decision, not a
 * rendered component. The numbers below are that phone — a ~1116pt app area with the
 * keyboard taking it to ~750.
 *
 * Also runs as `npm test` in this package.
 */
import assert from "node:assert/strict";
import test from "node:test";

// The real source, imported straight in: node 24 strips the types, so there is no build
// step and no second copy of the rule to drift out of step with it.
import { shellHeight } from "./viewport.ts";

test("the keyboard shrinks the shell while a field has focus", () => {
  // iOS Terms screen: without this the email field and the Accept button sit behind the
  // keyboard, which is the report this shrinking was added for.
  assert.equal(shellHeight({ stable: 1116, visual: 750, typing: true }), 750);
});

test("a stale small visual viewport cannot shrink the shell once typing has stopped", () => {
  // THE BUG. Android closes the keyboard without always firing visualViewport.resize, so
  // `visual` is still reporting the keyboard-open height. Sizing to it parked the tab bar
  // mid-screen with dead space under it, for the rest of the session.
  assert.equal(shellHeight({ stable: 1116, visual: 750, typing: false }), 1116);
});

test("the shell never exceeds Telegram's own stable height", () => {
  // The opposite direction, and the reason `stable` is always in the running: 100dvh
  // inside the Telegram webview can be taller than the visible area, which pushes the tab
  // bar off the bottom — the complaint that put --tg-vh here in the first place.
  assert.equal(shellHeight({ stable: 900, visual: 1200, typing: true }), 900);
});

test("no Telegram and no typing falls back to the caller's 100dvh", () => {
  // A bare browser. 100dvh is right there, and it is never the stuck-short value.
  assert.equal(shellHeight({ visual: 800, typing: false }), null);
  assert.equal(shellHeight({ typing: true }), null);
});

test("an older webview with no visualViewport still gets a height", () => {
  assert.equal(shellHeight({ stable: 1116, typing: true }), 1116);
});

test("zero and negative readings are ignored rather than believed", () => {
  // Telegram reports 0 before the app has been measured; a shell of 0px is a blank screen.
  assert.equal(shellHeight({ stable: 0, visual: 750, typing: true }), 750);
  assert.equal(shellHeight({ stable: 1116, visual: 0, typing: true }), 1116);
  assert.equal(shellHeight({ stable: 0, visual: 0, typing: true }), null);
});
