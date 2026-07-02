import clsx from "clsx";
import type { HTMLAttributes } from "react";

interface NumProps extends HTMLAttributes<HTMLSpanElement> {
  value: number | string;
  /** Prefixes with $, formatted to 2 decimals when value is numeric. */
  usd?: boolean;
  /** Appends %. */
  percent?: boolean;
}

/** Every money/count/id/timestamp value in the app renders through this
 * component so it always gets font-mono + tabular-nums — see design-spec.md
 * §2. Keeps that rule impossible to forget in a random screen. */
export function Num({ value, usd, percent, className, ...rest }: NumProps) {
  let display: string;
  if (usd && typeof value === "number") {
    display = `$${value.toFixed(2)}`;
  } else if (percent && typeof value === "number") {
    display = `${value}%`;
  } else {
    display = String(value);
  }
  return (
    <span className={clsx("font-mono tabular-nums", className)} {...rest}>
      {display}
    </span>
  );
}
