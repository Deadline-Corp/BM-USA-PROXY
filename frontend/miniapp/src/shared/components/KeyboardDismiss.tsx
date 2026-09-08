import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { strings } from "../strings";

/**
 * A way out of the keyboard, wherever the field is.
 *
 * iOS gives a number pad no return key, so "how many proxies" and the auto-rotation
 * interval had no way to put their own keyboard away — and tapping outside a field inside
 * a sheet closes the sheet, losing what was chosen. A Done button in the sheet header
 * covered the sheets and nothing else: the auto-rotation field sits inline on the access
 * page, where there is no header to put it in.
 *
 * So it lives above the keyboard instead of inside any one screen. Mounted once, watches
 * focus for the whole app, and appears for every field there is.
 *
 * Positioned against `visualViewport` rather than the page. On iOS the keyboard does not
 * resize the layout viewport, it only covers it, so `bottom: 0` would put this underneath
 * the keys. `visualViewport.height + offsetTop` is where the covered part begins, which is
 * exactly the line to sit on.
 */
export function KeyboardDismiss() {
  const [gap, setGap] = useState<number | null>(null);

  useEffect(() => {
    const isField = (el: Element | null): el is HTMLElement =>
      el instanceof HTMLElement && el.matches("input, textarea, [contenteditable]");

    const place = () => {
      if (!isField(document.activeElement)) {
        setGap(null);
        return;
      }
      const vv = window.visualViewport;
      if (!vv) {
        // No visualViewport (older webviews): the keyboard's height is unknowable, so the
        // bar would have to guess where to sit. Better absent than floating over content.
        setGap(null);
        return;
      }
      const covered = Math.max(0, window.innerHeight - (vv.height + vv.offsetTop));
      // A keyboard covers a real fraction of the screen. Anything smaller is the address
      // bar or a rounding wobble, and pinning a button to it would leave one hovering over
      // the page with nothing to dismiss.
      setGap(covered > 120 ? covered : null);
    };

    // The keyboard animates, and iOS reports the viewport partway through — so this is
    // asked again on a delay as well as on the event.
    const placeSoon = () => {
      place();
      window.setTimeout(place, 120);
      window.setTimeout(place, 400);
    };

    document.addEventListener("focusin", placeSoon);
    document.addEventListener("focusout", placeSoon);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    place();
    return () => {
      document.removeEventListener("focusin", placeSoon);
      document.removeEventListener("focusout", placeSoon);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
    };
  }, []);

  if (gap === null) return null;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 z-[60] flex justify-end px-3 pb-2"
      style={{ bottom: gap }}
    >
      {/* onPointerDown + preventDefault keeps the field focused through the press, so the
          button is still mounted when the click lands. Without it the blur removes the bar
          first and the click goes to whatever is underneath — which is how the sheet's
          Done button used to close the sheet instead of the keyboard. */}
      <button
        type="button"
        className="pointer-events-auto flex items-center gap-1.5 rounded-full border border-border-2 bg-surface px-3.5 py-2 text-[13px] font-semibold text-text-2 shadow-[0_6px_18px_-6px_rgba(18,27,64,.35)] active:bg-surface-2"
        onPointerDown={(e) => e.preventDefault()}
        onClick={() => {
          const el = document.activeElement;
          if (el instanceof HTMLElement) el.blur();
        }}
      >
        <ChevronDown size={15} aria-hidden="true" />
        {strings.common.hideKeyboard}
      </button>
    </div>
  );
}
