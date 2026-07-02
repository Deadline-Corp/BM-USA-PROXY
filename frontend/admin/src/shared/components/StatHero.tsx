import type { ReactNode } from "react";
import { IconArrowDown, IconArrowUp } from "@/shared/components/icons";

interface StatHeroProps {
  label: string;
  value: ReactNode;
  deltaPct?: number;
  deltaLabel?: string;
  /** 0-1 normalized points for the inline sparkline (left→right). */
  sparkline?: number[];
  sparklineLabels?: string[];
}

/** kpi-primary block: hero stat + delta pill + hand-drawn inline SVG
 * sparkline with an accent gradient fill, matching the prototype exactly
 * (recharts is deliberately not used here — see design-spec.md §8). */
export function StatHero({ label, value, deltaPct, deltaLabel, sparkline, sparklineLabels }: StatHeroProps) {
  const isUp = (deltaPct ?? 0) >= 0;
  const path = sparkline && sparkline.length > 1 ? buildSparkPath(sparkline) : null;

  return (
    <div className="bg-surface border border-border rounded-lg shadow px-5 py-[18px] flex flex-col">
      <span className="text-[.74rem] uppercase tracking-[.1em] text-text-3 font-semibold">{label}</span>
      <span className="font-mono tabular-nums text-[2.35rem] font-semibold tracking-[-0.02em] leading-none mt-1.5 text-text">
        {value}
      </span>
      {deltaPct !== undefined && (
        <div className="flex items-center gap-2 mt-2">
          <span
            className={
              "inline-flex items-center gap-1 font-mono tabular-nums text-[.78rem] font-semibold px-[7px] py-[2px] rounded-full " +
              (isUp ? "text-success bg-success-soft" : "text-danger bg-danger-soft")
            }
          >
            {isUp ? <IconArrowUp className="w-3 h-3" /> : <IconArrowDown className="w-3 h-3" />}
            {Math.abs(deltaPct)}%
          </span>
          {deltaLabel && <span className="text-text-3 text-[.8rem]">{deltaLabel}</span>}
        </div>
      )}
      {path && (
        <div className="mt-auto pt-3.5">
          <svg viewBox="0 0 320 64" preserveAspectRatio="none" width="100%" height={56} aria-hidden="true">
            <defs>
              <linearGradient id="sparkFillHero" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#195079" stopOpacity={0.16} />
                <stop offset="100%" stopColor="#195079" stopOpacity={0} />
              </linearGradient>
            </defs>
            <path d={`${path.line} L316 64 L4 64 Z`} fill="url(#sparkFillHero)" />
            <path
              d={path.line}
              fill="none"
              stroke="#195079"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx={path.lastX} cy={path.lastY} r={3.5} fill="#195079" />
          </svg>
          {sparklineLabels && (
            <div className="flex items-center justify-between text-text-3 text-[.68rem] mt-1">
              {sparklineLabels.map((l) => (
                <span key={l}>{l}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function buildSparkPath(points: number[]) {
  const w = 312;
  const left = 4;
  const top = 8;
  const height = 42;
  const step = points.length > 1 ? w / (points.length - 1) : 0;
  const coords = points.map((p, i) => {
    const x = left + step * i;
    const y = top + (1 - Math.min(1, Math.max(0, p))) * height;
    return { x, y };
  });
  const line = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
  const last = coords[coords.length - 1];
  return { line, lastX: last.x, lastY: last.y };
}
