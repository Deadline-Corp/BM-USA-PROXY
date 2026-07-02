import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import clsx from "clsx";
import { IconAlertCircle, IconAlertTriangle, IconCheckPlain, IconX } from "@/shared/components/icons";

type ToastTone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  push: (message: string, tone?: ToastTone) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const toneStyles: Record<ToastTone, { bg: string; icon: ReactNode }> = {
  success: {
    bg: "border-success-line bg-surface",
    icon: <IconCheckPlain className="w-4 h-4 text-success flex-none" />,
  },
  error: {
    bg: "border-danger-line bg-surface",
    icon: <IconAlertTriangle className="w-4 h-4 text-danger flex-none" />,
  },
  info: {
    bg: "border-accent-line bg-surface",
    icon: <IconAlertCircle className="w-4 h-4 text-accent flex-none" />,
  },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = ++idRef.current;
      setItems((prev) => [...prev, { id, tone, message }]);
      window.setTimeout(() => dismiss(id), 4200);
    },
    [dismiss],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      success: (message: string) => push(message, "success"),
      error: (message: string) => push(message, "error"),
      info: (message: string) => push(message, "info"),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-5 right-5 z-[100] flex flex-col gap-2 w-[min(360px,calc(100vw-40px))]">
        {items.map((item) => (
          <div
            key={item.id}
            role="status"
            className={clsx(
              "animate-fade-in flex items-start gap-2.5 rounded-xl border shadow-lg px-4 py-3 text-[.86rem] text-text",
              toneStyles[item.tone].bg,
            )}
          >
            {toneStyles[item.tone].icon}
            <span className="flex-1 min-w-0">{item.message}</span>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              className="flex-none text-text-3 hover:text-text transition-colors duration-150 ease-brand"
              aria-label="Dismiss"
            >
              <IconX className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
