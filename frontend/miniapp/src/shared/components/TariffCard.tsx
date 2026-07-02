import type { ReactNode } from "react";
import { Check, Sparkles } from "lucide-react";
import clsx from "clsx";
import { Chip } from "./Chip";

interface TariffCardProps {
  name: string;
  meta: string;
  price: ReactNode;
  priceSub: string;
  isFree?: boolean;
  highlight?: boolean;
  features: string[];
  badge?: ReactNode;
  action: ReactNode;
  extraBadges?: ReactNode;
}

/** Port of the demo's .mcatalog-plan / .mcatalog-plan.is-highlight. */
export function TariffCard({
  name,
  meta,
  price,
  priceSub,
  isFree,
  highlight,
  features,
  badge,
  action,
  extraBadges,
}: TariffCardProps) {
  return (
    <div
      className={clsx(
        "flex flex-col gap-2.5 rounded-lg border p-4 shadow-card transition-colors duration-[180ms] ease-out",
        highlight
          ? "border-accent bg-surface-2 shadow-[0_0_0_1px_rgba(25,80,121,.28),0_16px_40px_-22px_rgba(20,50,74,.14)]"
          : "border-border bg-surface",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <b className="font-head text-[16px] font-semibold leading-tight tracking-tight text-text">{name}</b>
          <small className="text-xs leading-snug text-text-3">{meta}</small>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-0.5">
          <span
            className={clsx(
              "num text-[22px] font-bold leading-none",
              isFree ? "text-success" : highlight ? "text-accent" : "text-text",
            )}
          >
            {price}
          </span>
          <span className="text-right text-[11px] text-text-3">{priceSub}</span>
        </div>
      </div>

      {extraBadges}

      <div className="flex flex-col gap-1.5">
        {features.map((feature) => (
          <span key={feature} className="flex items-center gap-1.5 text-[13px] leading-snug text-text-2">
            <Check size={14} className="shrink-0 text-accent" />
            {feature}
          </span>
        ))}
      </div>

      {badge ?? (
        <Chip tone="success" className="self-start border-success/[.28] bg-success/10 text-[11px]">
          <Sparkles size={11} />
          Auto-issued
        </Chip>
      )}

      {action}
    </div>
  );
}
