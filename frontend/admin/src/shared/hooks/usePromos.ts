import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { promoApi } from "@/shared/api/endpoints";
import type { ListParams, PromoCodeBody } from "@/shared/api/types";

const key = ["promo-codes"];
const usageKey = ["promo-usage"];

export function usePromoCodes() {
  return useQuery({ queryKey: key, queryFn: promoApi.list });
}

export function useCreatePromoCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PromoCodeBody) => promoApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });
}

export function useDeletePromoCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => promoApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });
}

/** Who used what, and on which plan. Its own key rather than a slice of the codes query:
 *  the two are paged separately and creating a code does not change the history. */
export function usePromoUsage(params: ListParams) {
  return useQuery({
    queryKey: [...usageKey, params],
    queryFn: () => promoApi.usage(params),
    placeholderData: (prev) => prev,
  });
}
