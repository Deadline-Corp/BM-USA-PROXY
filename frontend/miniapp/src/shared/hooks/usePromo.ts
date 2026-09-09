import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PromoCheckBody, PromoQuote } from "../api/types";

/**
 * What a code is worth on this order, before anything is created.
 *
 * A mutation rather than a query even though it writes nothing: it runs when the buyer
 * presses Apply, and caching a rejection ("already used") would keep showing it after the
 * reason had gone.
 */
export function usePromoCheck() {
  return useMutation({
    mutationFn: (body: PromoCheckBody) => api.post<PromoQuote>("/promo/check", body),
  });
}
