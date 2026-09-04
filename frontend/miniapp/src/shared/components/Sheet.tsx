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
  const [typing, setTyping] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) setTyping(false);
  }, [open]);

  // Whether a field inside this sheet holds focus — i.e. whether a keyboard is up.
  // Read from the DOM rather than tracked per field, so every sheet gets this without
  // each screen remembering to wire it.
  const syncTyping = () => {
    const el = document.activeElement;
    setTyping(
      el instanceof HTMLElement &&
        !!panel.current?.contains(el) &&
        el.matches("input, textarea, [contenteditable]"),
    );
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal="true" aria-label={title}>
      <div
        className="absolute inset-0 bg-text/40 animate-[m-fade_.2s_cubic-bezier(.16,1,.3,1)]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panel}
        onFocus={syncTyping}
        onBlur={() => window.setTimeout(syncTyping, 0)}
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
          {/* iOS gives a number pad no return key at all, so a field like "how many
              proxies" has no way to dismiss its own keyboard — the client had to tap
              outside, which inside a sheet closes the sheet. Shown only while something in
              here is focused, and it sits in the header, which the keyboard never covers.
              onPointerDown + preventDefault keeps the focus long enough for the click to
              land; without it the blur unmounts the button first and nothing happens. */}
          {typing ? (
            <button
              type="button"
              className="shrink-0 rounded-lg border border-accent/40 bg-accent/[.08] px-3 py-1.5 text-[13px] font-semibold text-accent transition-colors hover:bg-accent/[.14] focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              onPointerDown={(e) => {
                e.preventDefault();
                (document.activeElement as HTMLElement | null)?.blur();
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
