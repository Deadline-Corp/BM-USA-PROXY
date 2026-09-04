/**
 * Which city and carrier a buyer can still be given, read off the catalogue's own counts.
 *
 * The two pickers narrow each other. Offered independently they produce combinations that
 * cannot be served — New York with AT&T when every AT&T phone is elsewhere — and the buyer
 * only learns that from a dead Buy button, or, on the swap sheet, from an error after
 * pressing it. The backend already sends `free` per carrier per city (see
 * services/catalog.py); nothing here counts anything, it only reads that.
 *
 * One module for both screens because they were written weeks apart and would otherwise
 * disagree about what "available" means — which is how the buy screen ends up offering
 * what the swap sheet hides.
 */

import type { Carrier, Catalog, CatalogLocation, LocationFree } from "../api/types";

export const ANY_CHOICE = "any" as const;
export type AnyChoice = typeof ANY_CHOICE;

/** `free` is keyed by carrier name plus the literal "any" for the city's own total. */
function readFree(free: LocationFree | undefined, carrier: Carrier | AnyChoice): number {
  return Number(free?.[carrier === ANY_CHOICE ? "any" : carrier] ?? 0);
}

/** How many phones are free under this pair. "Any city" is the catalogue's own total,
 *  which includes phones with no city recorded — they can only be handed out that way. */
export function freeFor(
  catalog: Catalog | undefined,
  locationId: number | AnyChoice,
  carrier: Carrier | AnyChoice,
): number {
  if (!catalog) return 0;
  if (locationId === ANY_CHOICE) return readFree(catalog.any_city_free, carrier);
  return readFree(catalog.locations.find((l) => l.id === locationId)?.free, carrier);
}

/** The carriers that can actually be given in this city. */
export function carriersAvailable(
  catalog: Catalog | undefined,
  locationId: number | AnyChoice,
): Carrier[] {
  if (!catalog) return [];
  return catalog.carriers.filter((c) => freeFor(catalog, locationId, c) > 0);
}

/** The cities that can actually serve this carrier. */
export function locationsAvailable(
  catalog: Catalog | undefined,
  carrier: Carrier | AnyChoice,
): CatalogLocation[] {
  if (!catalog) return [];
  return catalog.locations.filter((l) => readFree(l.free, carrier) > 0);
}

/** The carrier to hold after the city changed: the same one if it is still servable there,
 *  otherwise "any". Leaving a now-impossible carrier selected is what produced the dead
 *  Buy button — the control still reads AT&T while nothing behind it can be sold. */
export function carrierAfterCityChange(
  catalog: Catalog | undefined,
  locationId: number | AnyChoice,
  carrier: Carrier | AnyChoice,
): Carrier | AnyChoice {
  if (carrier === ANY_CHOICE) return ANY_CHOICE;
  return freeFor(catalog, locationId, carrier) > 0 ? carrier : ANY_CHOICE;
}
