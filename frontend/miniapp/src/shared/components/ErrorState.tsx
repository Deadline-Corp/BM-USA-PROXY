import { AlertTriangle } from "lucide-react";
import clsx from "clsx";
import { strings } from "../strings";
import { Button } from "./Button";

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}

/** Inline error message + retry button — used by every data-fetching screen. */
export function ErrorState({ message, onRetry, className, compact }: ErrorStateProps) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center gap-3 rounded-lg border border-danger/30 bg-danger/[.05] text-center",
        compact ? "px-4 py-4" : "px-5 py-8",
        className,
      )}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-danger/10 text-danger">
        <AlertTriangle size={18} />
      </span>
      <p className="max-w-[260px] text-[13px] leading-relaxed text-text-2">
        {message ?? strings.errors.generic}
      </p>
      {onRetry ? (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          {strings.common.retry}
        </Button>
      ) : null}
    </div>
  );
}
