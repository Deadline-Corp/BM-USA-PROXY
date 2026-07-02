import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";
import { IconX } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "default" | "lg";
}

export function Modal({ open, onClose, title, subtitle, children, footer, size = "default" }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-[rgba(20,50,74,.32)] animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        className={clsx(
          "relative z-10 w-full bg-surface border border-border rounded-lg shadow-lg animate-fade-in max-h-[90vh] flex flex-col",
          size === "lg" ? "max-w-[640px]" : "max-w-[480px]",
        )}
      >
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-border flex-none">
          <div className="flex flex-col gap-0.5 min-w-0">
            <h3 className="text-base">{title}</h3>
            {subtitle && <span className="text-[.78rem] text-text-3">{subtitle}</span>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={strings.common.close}
            className="flex-none w-8 h-8 grid place-items-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-text transition-colors duration-150 ease-brand"
          >
            <IconX className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-5 overflow-y-auto flex-1">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2.5 px-5 py-4 border-t border-border flex-none">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
