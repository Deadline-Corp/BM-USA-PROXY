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
    <div className={clsx("mt-1 rounded-lg border-2 border-dashed border-accent/[.22] px-6 py-5 text-center", className)}>
      <div className="mx-auto mb-2.5 flex h-12 w-12 items-center justify-center rounded-full bg-surface text-accent shadow-soft">
        {icon}
      </div>
      <h3 className="mb-1 font-head text-[19px] font-bold tracking-tight text-text">{title}</h3>
      {body ? <p className="mx-auto mb-3.5 max-w-[300px] text-[14.5px] leading-relaxed text-text-2">{body}</p> : null}
      {action ? <div className="flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
