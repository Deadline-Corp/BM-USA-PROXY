import type { ReactNode } from "react";
import clsx from "clsx";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
  className?: string;
}

/** Explicit empty-state block with optional CTA — never render a blank screen. */
export function EmptyState({ icon, title, body, action, className }: EmptyStateProps) {
  return (
    <div className={clsx("mt-1 rounded-lg border border-dashed border-border-2 px-5 py-8 text-center", className)}>
      <div className="mx-auto mb-3.5 flex h-12 w-12 items-center justify-center rounded-full border border-border bg-surface-2 text-text-3">
        {icon}
      </div>
      <h3 className="mb-1.5 font-head text-[15px] font-semibold tracking-tight text-text">{title}</h3>
      {body ? <p className="mx-auto mb-4 max-w-[260px] text-[13px] leading-relaxed text-text-2">{body}</p> : null}
      {action ? <div className="flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
