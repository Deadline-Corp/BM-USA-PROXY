import clsx from "clsx";
import { useCountdown } from "../hooks/useCountdown";
import { formatDuration } from "../lib/format";
import { strings } from "../strings";
import { Num } from "./Num";

interface CountdownBadgeProps {
  expiresAt: string | null | undefined;
  /** Seconds remaining at/under which the value switches to the warning color. Default 1h. */
  warnThresholdSeconds?: number;
  className?: string;
  valueClassName?: string;
}

/** Ticking countdown to an ISO timestamp. Switches to a warning state under the threshold. */
export function CountdownBadge({
  expiresAt,
  warnThresholdSeconds = 3600,
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
          "text-[19px] font-medium text-text",
          isWarn && "text-warning",
          isExpired && "text-text-3",
          valueClassName,
        )}
      >
        {isExpired ? strings.common.expired : formatDuration(remainingSeconds)}
      </Num>
    </span>
  );
}
