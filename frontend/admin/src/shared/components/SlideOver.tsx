import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";
import { IconX } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

interface SlideOverProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  headerAccessory?: ReactNode;
}

export function SlideOver({ open, onClose, title, subtitle, children, footer, headerAccessory }: SlideOverProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return createPortal(
    <>
      <div
        className={clsx(
          "fixed inset-0 z-[55] bg-[rgba(20,50,74,.28)] transition-opacity duration-200 ease-brand",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-modal="true"
        className={clsx(
          "fixed top-0 right-0 z-[60] h-screen w-[min(440px,92vw)] bg-surface border-l border-border shadow-lg",
          "flex flex-col transition-transform duration-200 ease-brand",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex items-start justify-between gap-3 px-5 py-[18px] border-b border-border flex-none">
          <div className="flex flex-col gap-1 min-w-0">
            <h3 className="text-base truncate">{title}</h3>
            {subtitle && <div className="text-[.78rem] text-text-3">{subtitle}</div>}
          </div>
          <div className="flex items-center gap-2 flex-none">
            {headerAccessory}
            <button
              type="button"
              onClick={onClose}
              aria-label={strings.common.close}
              className="w-8 h-8 grid place-items-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-text transition-colors duration-150 ease-brand"
            >
              <IconX className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="px-5 py-5 overflow-y-auto flex-1">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2.5 px-5 py-4 border-t border-border flex-none">
            {footer}
          </div>
        )}
      </aside>
    </>,
    document.body,
  );
}
