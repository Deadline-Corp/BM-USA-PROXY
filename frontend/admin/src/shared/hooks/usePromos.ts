import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { promoApi } from "@/shared/api/endpoints";
import type { PromoCodeBody } from "@/shared/api/types";

const key = ["promo-codes"];

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
