/**
 * The shell-height rule. `npm test` in this package, or
 * `node --test src/shared/lib/viewport.test.mjs`.
 *
 * A plain node test rather than a framework: this file exists because of two reported bugs
 * on one Android phone, and the thing worth pinning down is a four-line decision, not a
 * rendered component. The numbers are that phone — a 1116px webview, a shell that came out
 * at ~660px, and ~750px left when the keyboard is up.
 */
import assert from "node:assert/strict";
import test from "node:test";

// The real source, imported straight in: node 24 strips the types, so there is no build
// step and no second copy of the rule to drift out of step with it.
import { shellHeight } from "./viewport.ts";

test("the shell is the window it is laid out in", () => {
  assert.equal(shellHeight({ inner: 1116, visual: 1116, typing: false }), 1116);
});

test("Telegram's own viewport figure cannot make the shell short", () => {
  // THE SECOND BUG, and the reason `stable` is not a parameter any more. Telegram reported
  // ~660 on a 1116px webview — its own units, its own window, unverifiable from here — and
  // the tab bar sat 450px off the bottom with dead space under it. There is now no argument
  // that can express that: whatever Telegram says, the shell is the window.
  // Handed the number anyway, the way the old caller did: it changes nothing.
  assert.equal(shellHeight({ inner: 1116, stable: 660, visual: 1116, typing: false }), 1116);
  assert.equal(shellHeight({ inner: 1116, stable: 660, visual: 750, typing: true }), 750);
});

test("the keyboard shrinks the shell while a field has focus", () => {
  // iOS Terms screen: without this the email field and the Accept button sit behind the
  // keyboard, which is the report the shrinking was added for. innerHeight does not move
  // on iOS when the keyboard opens — only the visual viewport does.
  assert.equal(shellHeight({ inner: 1116, visual: 750, typing: true }), 750);
});

test("a stale small visual viewport cannot shrink the shell once typing has stopped", () => {
  // THE FIRST BUG. Android closes the keyboard without always firing visualViewport.resize,
  // so `visual` still reports the keyboard-open height. Believing it parked the tab bar
  // mid-screen for the rest of the session.
  assert.equal(shellHeight({ inner: 1116, visual: 750, typing: false }), 1116);
});

test("a visual viewport larger than the window never stretches the shell", () => {
  assert.equal(shellHeight({ inner: 900, visual: 1200, typing: true }), 900);
});

test("no window height falls back to the caller's 100dvh", () => {
  assert.equal(shellHeight({ visual: 800, typing: false }), null);
  assert.equal(shellHeight({ inner: 0, visual: 800, typing: true }), null);
});

test("an older webview with no visualViewport still gets a height", () => {
  assert.equal(shellHeight({ inner: 1116, typing: true }), 1116);
});

test("zero and negative readings are ignored rather than believed", () => {
  assert.equal(shellHeight({ inner: 1116, visual: 0, typing: true }), 1116);
  assert.equal(shellHeight({ inner: 1116, visual: -5, typing: true }), 1116);
});
