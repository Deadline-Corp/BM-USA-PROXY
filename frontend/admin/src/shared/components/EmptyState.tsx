import type { ReactNode } from "react";
import { IconInbox } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

interface EmptyStateProps {
  title?: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ title = strings.common.noResults, hint = strings.common.noResultsHint, icon, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 px-6 text-center">
      <div className="w-11 h-11 grid place-items-center rounded-xl bg-surface-2 border border-border text-text-3">
        {icon ?? <IconInbox className="w-5 h-5" />}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-[.92rem] font-medium text-text">{title}</span>
        <span className="text-[.8rem] text-text-3">{hint}</span>
      </div>
      {action}
    </div>
  );
}
