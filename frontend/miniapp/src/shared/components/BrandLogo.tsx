/**
 * Two-tone US-flag star app mark (brand blue left / brand red right),
 * matching the bmusproxy.com logo motif. Colors come from Tailwind
 * fill utilities so the palette stays token-driven.
 */
export function BrandLogo({ size = 24 }: { size?: number }) {
  const star =
    "M12 2l2.94 6.32 6.91.75-5.12 4.7 1.39 6.8L12 17.27l-6.12 3.3 1.39-6.8-5.12-4.7 6.91-.75L12 2z";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d={star} className="fill-accent" />
      <clipPath id="bm-logo-star-right">
        <rect x="12" y="0" width="12" height="24" />
      </clipPath>
      <path d={star} className="fill-red" clipPath="url(#bm-logo-star-right)" />
    </svg>
  );
}
