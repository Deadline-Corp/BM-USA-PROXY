import type { ElementType, ReactNode } from "react";
import clsx from "clsx";

interface NumProps {
  children: ReactNode;
  as?: ElementType;
  className?: string;
}

/**
 * Reusable text style for money, timers, and credentials — Roboto Mono with
 * font-variant-numeric: tabular-nums. Use this instead of repeating inline
 * styles anywhere a number-like value is rendered.
 */
export function Num({ children, as: Tag = "span", className }: NumProps) {
  return <Tag className={clsx("num", className)}>{children}</Tag>;
}
