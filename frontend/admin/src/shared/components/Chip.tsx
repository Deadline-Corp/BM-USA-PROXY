import clsx from "clsx";
import type { HTMLAttributes } from "react";

export function Chip({ className, ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 h-6 px-[9px] rounded-full bg-surface-2 border border-border text-[.74rem] font-medium text-text-2 whitespace-nowrap",
        className,
      )}
      {...rest}
    />
  );
}
