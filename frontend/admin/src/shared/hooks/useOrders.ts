import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ordersApi } from "@/shared/api/endpoints";
import type { ListParams, MarkPaidRequest, RefundRequest, ResolveOrderRequest } from "@/shared/api/types";

export function useOrdersList(params: ListParams) {
  return useQuery({
    queryKey: ["orders", params],
    queryFn: () => ordersApi.list(params),
  });
}

export function useManualReviewOrders() {
  return useQuery({
    queryKey: ["orders", "manual-review"],
    queryFn: ordersApi.manualReview,
  });
}

export function useOrder(id: string | null) {
  return useQuery({
    queryKey: ["orders", "detail", id],
    queryFn: () => ordersApi.get(id as string),
    enabled: id !== null,
  });
}

export function useResolveOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ResolveOrderRequest }) => ordersApi.resolve(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useRefundOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: RefundRequest }) => ordersApi.refund(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });
}

export function useMarkPaidOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: MarkPaidRequest }) => ordersApi.markPaid(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });
}
