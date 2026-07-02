import type { HTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  variant?: "default" | "hero";
}

/** Port of the demo's .m-card / .m-hero. */
export function Card({ children, variant = "default", className, ...rest }: CardProps) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-border bg-surface",
        variant === "default" && "p-[15px] shadow-soft",
        variant === "hero" &&
          "rounded-xl p-[17px] shadow bg-gradient-to-b from-accent/[.06] to-transparent to-70%",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

interface SectionLabelProps {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** Port of the demo's .m-label. */
export function SectionLabel({ children, action, className }: SectionLabelProps) {
  return (
    <p className={clsx("mx-0.5 mb-2 flex items-center justify-between text-[11px] font-medium uppercase tracking-[.09em] text-text-3", className)}>
      <span>{children}</span>
      {action}
    </p>
  );
}
