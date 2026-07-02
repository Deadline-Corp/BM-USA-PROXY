import type { ReactNode } from "react";
import { useEffect } from "react";
import { X } from "lucide-react";
import clsx from "clsx";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}

/** Bottom-sheet modal for pickers (city / carrier / tariff selection). */
export function Sheet({ open, onClose, title, children, footer }: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal="true" aria-label={title}>
      <div
        className="absolute inset-0 bg-[#14324A]/40 animate-[m-fade_.2s_cubic-bezier(.16,1,.3,1)]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={clsx(
          "relative z-10 flex max-h-[80vh] w-full max-w-[420px] flex-col rounded-t-xl border border-b-0 border-border bg-surface shadow-[0_-16px_40px_-16px_rgba(20,50,74,.28)]",
          "animate-[m-fade_.22s_cubic-bezier(.16,1,.3,1)]",
        )}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3.5">
          <h2 className="font-head text-[15px] font-semibold tracking-tight text-text">{title}</h2>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-surface-2 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
