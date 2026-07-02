import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useRef, useState } from "react";
import { CheckCircle2, AlertCircle } from "lucide-react";
import clsx from "clsx";

type ToastTone = "success" | "error";

interface ToastState {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastContextValue {
  showToast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idRef = useRef(0);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    idRef.current += 1;
    setToast({ id: idRef.current, message, tone });
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setToast(null), 2600);
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-[76px] z-[60] flex justify-center px-4" aria-live="polite">
        {toast ? (
          <div
            key={toast.id}
            className={clsx(
              "pointer-events-auto flex max-w-[340px] items-center gap-2 rounded-lg border px-3.5 py-2.5 text-[12.5px] font-medium shadow animate-[m-fade_.2s_cubic-bezier(.16,1,.3,1)]",
              toast.tone === "success"
                ? "border-success/30 bg-surface text-text"
                : "border-danger/30 bg-surface text-text",
            )}
          >
            {toast.tone === "success" ? (
              <CheckCircle2 size={16} className="shrink-0 text-success" />
            ) : (
              <AlertCircle size={16} className="shrink-0 text-danger" />
            )}
            {toast.message}
          </div>
        ) : null}
      </div>
    </ToastContext.Provider>
  );
}
