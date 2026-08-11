import clsx from "clsx";
import { useCountdown } from "../hooks/useCountdown";
import { formatDuration, formatTimeLeft } from "../lib/format";
import { strings } from "../strings";
import { Num } from "./Num";

interface CountdownBadgeProps {
  expiresAt: string | null | undefined;
  /** Seconds remaining at/under which the value switches to the warning color. Default 1h. */
  warnThresholdSeconds?: number;
  /**
   * `clock` — `MM:SS`, for the payment window: one hour at most, and the seconds are the
   * point. `remaining` — `4w 1d 23h 55m 31s`, for how much of an access is left, where a
   * stopwatch would have to count past seven hundred hours to say "about a month".
   */
  variant?: "clock" | "remaining";
  className?: string;
  valueClassName?: string;
}

/** Ticking countdown to an ISO timestamp. Switches to a warning state under the threshold. */
export function CountdownBadge({
  expiresAt,
  warnThresholdSeconds = 3600,
  variant = "clock",
  className,
  valueClassName,
}: CountdownBadgeProps) {
  const remainingMs = useCountdown(expiresAt);
  const remainingSeconds = Math.floor(remainingMs / 1000);
  const isExpired = !expiresAt || remainingMs <= 0;
  const isWarn = !isExpired && remainingSeconds <= warnThresholdSeconds;

  return (
    <span className={className}>
      <Num
        className={clsx(
          "font-medium text-text whitespace-nowrap",
          // Five units are twice the characters of MM:SS, so the remaining-variant starts
          // smaller — at the clock's size it runs into the label beside it.
          variant === "remaining" ? "text-[15px]" : "text-[19px]",
          isWarn && "text-warning",
          isExpired && "text-text-3",
          valueClassName,
        )}
      >
        {isExpired
          ? strings.common.expired
          : variant === "remaining"
            ? formatTimeLeft(remainingSeconds)
            : formatDuration(remainingSeconds)}
      </Num>
    </span>
  );
}
