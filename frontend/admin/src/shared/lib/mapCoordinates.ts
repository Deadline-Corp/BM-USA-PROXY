// Static city→SVG-coordinate lookup for the Dashboard's inline US pool map.
// Coordinates are hand-placed on the prototype's 900x460 stylized silhouette
// viewBox (see demo/admin.html map-hero). Cities returned by /pool/summary
// that aren't in this table are still counted in the totals row but simply
// don't render a node on the map — see design-spec.md §5 "Map hero".
export interface CityCoord {
  x: number;
  y: number;
  labelDy: number;
}

export const CITY_COORDS: Record<string, CityCoord> = {
  "seattle-wa": { x: 150, y: 138, labelDy: -14 },
  "portland-or": { x: 142, y: 178, labelDy: 20 },
  "denver-co": { x: 372, y: 232, labelDy: -14 },
  "las-vegas-nv": { x: 230, y: 262, labelDy: 20 },
  "los-angeles-ca": { x: 174, y: 288, labelDy: 20 },
  "phoenix-az": { x: 266, y: 312, labelDy: 20 },
  "dallas-tx": { x: 468, y: 318, labelDy: 20 },
  "chicago-il": { x: 586, y: 198, labelDy: -14 },
  "miami-fl": { x: 708, y: 346, labelDy: 20 },
  "new-york-ny": { x: 792, y: 148, labelDy: -14 },
  "atlanta-ga": { x: 610, y: 300, labelDy: 20 },
  "houston-tx": { x: 480, y: 358, labelDy: 20 },
  "san-francisco-ca": { x: 116, y: 232, labelDy: -14 },
  "boston-ma": { x: 812, y: 118, labelDy: -14 },
};

/** Normalizes a "City, ST" or "City" + state pair into the lookup key used
 * above. Best-effort — falls back gracefully if the city isn't mapped. */
export function cityKey(city: string, state?: string | null): string {
  const slug = city
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return state ? `${slug}-${state.toLowerCase()}` : slug;
}
