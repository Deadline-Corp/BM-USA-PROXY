import type { ReactNode } from "react";
import clsx from "clsx";

interface StatCardProps {
  icon?: ReactNode;
  label: string;
  value: ReactNode;
  footer?: ReactNode;
  className?: string;
}

/** One cell of a kpi-cluster row. Render 3-5 of these inside a
 * `<StatClusterRow>` for the shared-shadow-with-dividers look from the
 * prototype's `.kpi-cluster` / `.kpi` classes. */
export function StatCard({ icon, label, value, footer, className }: StatCardProps) {
  return (
    <div className={clsx("flex flex-col gap-1.5 p-4 relative", className)}>
      <span className="flex items-center gap-1.5 text-[.72rem] text-text-3 font-semibold">
        {icon && <span className="w-[15px] h-[15px] text-text-3 [&_svg]:w-full [&_svg]:h-full">{icon}</span>}
        {label}
      </span>
      <span className="font-mono tabular-nums text-2xl font-semibold leading-[1.1] tracking-[-0.01em] text-text">
        {value}
      </span>
      {footer && <span className="text-[.74rem] text-text-2">{footer}</span>}
    </div>
  );
}

export function StatClusterRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={clsx(
        "bg-surface border border-border rounded-lg shadow grid divide-x divide-border",
        className,
      )}
      style={{ gridTemplateColumns: `repeat(${Array.isArray(children) ? children.length : 1}, 1fr)` }}
    >
      {children}
    </div>
  );
}
