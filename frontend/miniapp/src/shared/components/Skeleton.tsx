import clsx from "clsx";

interface SkeletonBlockProps {
  className?: string;
}

/** Base shimmer block — compose into context-specific skeletons below. */
function SkeletonBlock({ className }: SkeletonBlockProps) {
  return <div className={clsx("animate-pulse rounded bg-surface-2", className)} />;
}

/** Skeleton for the home hero access card. */
export function HeroCardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-soft">
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <SkeletonBlock className="h-[38px] w-[38px] shrink-0 rounded" />
          <div className="flex flex-col gap-1.5">
            <SkeletonBlock className="h-4 w-32" />
            <SkeletonBlock className="h-3 w-20" />
          </div>
        </div>
        <SkeletonBlock className="h-6 w-16 rounded-full" />
      </div>
      <div className="mt-3 flex gap-2">
        <SkeletonBlock className="h-6 w-20 rounded-full" />
        <SkeletonBlock className="h-6 w-16 rounded-full" />
      </div>
      <SkeletonBlock className="mt-3 h-11 rounded" />
      <SkeletonBlock className="mt-3 h-11 rounded" />
      <div className="mt-3 flex gap-2">
        <SkeletonBlock className="h-[42px] flex-1 rounded" />
        <SkeletonBlock className="h-[42px] flex-1 rounded" />
      </div>
    </div>
  );
}

/** Skeleton for the quick-action tile grid on Home. */
export function TileGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-[11px]">
      <SkeletonBlock className="h-[92px] rounded-lg" />
      <SkeletonBlock className="h-[92px] rounded-lg" />
      <SkeletonBlock className="col-span-2 h-[68px] rounded-lg" />
      <SkeletonBlock className="col-span-2 h-[68px] rounded-lg" />
    </div>
  );
}

/** Skeleton for a list of tariff/plan cards on Catalog. */
export function TariffListSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-2.5">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex flex-col gap-2.5 rounded-lg border border-border bg-surface p-4 shadow-card">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-1.5">
              <SkeletonBlock className="h-4 w-24" />
              <SkeletonBlock className="h-3 w-36" />
            </div>
            <SkeletonBlock className="h-6 w-14" />
          </div>
          <SkeletonBlock className="h-3 w-full" />
          <SkeletonBlock className="h-3 w-4/5" />
          <SkeletonBlock className="h-[42px] rounded" />
        </div>
      ))}
    </div>
  );
}

/** Skeleton for a row-based list (accesses, requests, payout history). */
export function RowListSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="flex flex-col">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 border-b border-border py-3 last:border-b-0">
          <SkeletonBlock className="h-9 w-9 shrink-0 rounded-lg" />
          <div className="flex flex-1 flex-col gap-1.5">
            <SkeletonBlock className="h-3.5 w-2/5" />
            <SkeletonBlock className="h-3 w-1/4" />
          </div>
          <SkeletonBlock className="h-3.5 w-10" />
        </div>
      ))}
    </div>
  );
}

/** Skeleton for the credential rows on the access detail screen. */
export function CredentialRowsSkeleton() {
  return (
    <div className="flex flex-col gap-1.5">
      {Array.from({ length: 4 }).map((_, i) => (
        <SkeletonBlock key={i} className="h-11 rounded" />
      ))}
    </div>
  );
}

/** Skeleton for accordion-style lists (FAQ). */
export function AccordionSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonBlock key={i} className="h-[52px] rounded" />
      ))}
    </div>
  );
}

/** Generic short text-line skeleton, for small isolated regions. */
export function TextLineSkeleton({ className }: SkeletonBlockProps) {
  return <SkeletonBlock className={clsx("h-4 w-24", className)} />;
}
