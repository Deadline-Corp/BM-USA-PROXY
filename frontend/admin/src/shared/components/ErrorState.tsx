import { IconAlertTriangle } from "@/shared/components/icons";
import { Button } from "@/shared/components/Button";
import { strings } from "@/shared/strings";

interface ErrorStateProps {
  title?: string;
  hint?: string;
  onRetry?: () => void;
}

export function ErrorState({ title = strings.common.errorTitle, hint = strings.common.errorHint, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 px-6 text-center">
      <div className="w-11 h-11 grid place-items-center rounded-xl bg-danger-soft border border-danger-line text-danger">
        <IconAlertTriangle className="w-5 h-5" />
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-[.92rem] font-medium text-text">{title}</span>
        <span className="text-[.8rem] text-text-3">{hint}</span>
      </div>
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          {strings.common.retry}
        </Button>
      )}
    </div>
  );
}
