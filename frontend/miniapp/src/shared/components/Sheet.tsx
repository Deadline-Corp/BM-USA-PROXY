import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import clsx from "clsx";
import { strings } from "../strings";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}

/** Bottom-sheet modal for pickers (city / carrier / tariff selection). */
export function Sheet({ open, onClose, title, children, footer }: SheetProps) {
  const panel = useRef<HTMLDivElement>(null);
  const backdropPress = useRef(false);
  const [hasField, setHasField] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  // Does this sheet contain anything that raises a keyboard? Asked once when it opens,
  // rather than tracked against focus.
  //
  // The focus-tracked version shipped and was broken: Done unmounted the instant it did its
  // job, so the click that followed the tap had no target left and closed the whole sheet,
  // losing the quantity and coin the buyer had just chosen. A control that removes itself
  // between the press and the click cannot be made to work by adjusting the timing — so it
  // stays mounted for as long as the sheet does, and is simply inert when nothing is
  // focused.
  useEffect(() => {
    if (!open) {
      setHasField(false);
      return;
    }
    setHasField(!!panel.current?.querySelector("input, textarea, [contenteditable]"));
  }, [open, children]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal="true" aria-label={title}>
      {/* Closes only when the gesture both started and ended here. A press that began
          inside the sheet — a drag off a field, or a synthetic click the webview delivers
          after the keyboard has already reflowed the page — must not dismiss it. */}
      <div
        className="absolute inset-0 bg-text/40 animate-[m-fade_.2s_cubic-bezier(.16,1,.3,1)]"
        onPointerDown={(e) => {
          backdropPress.current = e.target === e.currentTarget;
        }}
        onClick={(e) => {
          if (backdropPress.current && e.target === e.currentTarget) onClose();
          backdropPress.current = false;
        }}
        aria-hidden="true"
      />
      <div
        ref={panel}
        className={clsx(
          // Against the viewport the app is actually painted on, not `vh`. On iOS `vh` is
          // the large viewport and ignores the keyboard entirely, so a sheet sized to 80vh
          // stayed the same height while the visible area shrank under it — which is what
          // the client saw as the window growing when they tapped the quantity field.
          // `--tg-vh` is set in main.tsx from Telegram's viewport and visualViewport, the
          // smaller of the two, and it does track the keyboard.
          "relative z-10 flex max-h-[calc(var(--tg-vh,100dvh)*0.85)] w-full max-w-[420px] flex-col",
          "rounded-t-xl border border-b-0 border-border bg-surface shadow-[0_-16px_40px_-16px_rgba(18,27,64,.28)]",
          "animate-[m-fade_.22s_cubic-bezier(.16,1,.3,1)]",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3.5">
          <h2 className="min-w-0 flex-1 truncate font-head text-[17px] font-bold tracking-tight text-text">
            {title}
          </h2>
          {/* Dismisses the keyboard and does nothing else — it must not close the sheet or
              submit anything, because the buyer is mid-way through choosing and everything
              they have picked so far lives in this sheet.

              iOS gives a number pad no return key, so "how many proxies" has no other way
              to put the keyboard away; tapping outside would close the sheet and lose the
              choice. The header is the one place the keyboard never covers.

              Plain onClick, and mounted for the whole life of the sheet — see `hasField`. */}
          {hasField ? (
            <button
              type="button"
              className="shrink-0 rounded-lg border border-accent/40 bg-accent/[.08] px-3 py-1.5 text-[13px] font-semibold text-accent transition-colors hover:bg-accent/[.14] focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              onClick={() => {
                const el = document.activeElement;
                if (el instanceof HTMLElement) el.blur();
              }}
            >
              {strings.common.doneTyping}
            </button>
          ) : null}
          <button
            type="button"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-surface-2 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto px-4 py-3.5">{children}</div>
        {footer ? <div className="border-t border-border px-4 py-3.5">{footer}</div> : null}
      </div>
    </div>
  );
}
