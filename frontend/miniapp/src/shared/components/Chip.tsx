import type { ReactNode } from "react";
import clsx from "clsx";

type ChipTone = "default" | "accent" | "success" | "warn" | "danger";

interface ChipProps {
  children: ReactNode;
  tone?: ChipTone;
  className?: string;
}

const toneClasses: Record<ChipTone, string> = {
  default: "bg-surface-2 border-border text-text-2",
  accent: "bg-accent/10 border-accent/[.22] text-accent",
  success: "bg-surface-2 border-success/30 text-success",
  warn: "bg-surface-2 border-warning/30 text-warning",
  danger: "bg-surface-2 border-danger/30 text-danger",
};

/** Port of the demo's .m-chip. */
export function Chip({ children, tone = "default", className }: ChipProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[5px] text-[11.5px] font-medium",
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

interface DotProps {
  tone?: "online" | "warn" | "off" | "idle";
  className?: string;
}

const dotClasses: Record<NonNullable<DotProps["tone"]>, string> = {
  online: "bg-success shadow-[0_0_0_3px_rgba(30,158,106,.16)]",
  warn: "bg-warning shadow-[0_0_0_3px_rgba(217,144,33,.16)]",
  off: "bg-danger shadow-[0_0_0_3px_rgba(194,65,60,.16)]",
  idle: "bg-text-3",
};

/** Port of the demo's .dot / .dot-online / .dot-warn / .dot-off / .dot-idle. */
export function Dot({ tone = "online", className }: DotProps) {
  return <span className={clsx("inline-block h-2 w-2 shrink-0 rounded-full", dotClasses[tone], className)} />;
}
