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
        "rounded-lg border border-border/60 bg-surface",
        variant === "default" && "p-4 shadow-soft",
        variant === "hero" &&
          "rounded-xl p-5 shadow bg-gradient-to-b from-accent/[.06] to-transparent to-70%",
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
    <p className={clsx("mx-0.5 mb-2.5 flex items-center justify-between text-[12px] font-bold uppercase tracking-[.1em] text-accent", className)}>
      <span>{children}</span>
      {action}
    </p>
  );
}
