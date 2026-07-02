import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  CreateOrderBody,
  CreateOrderResponse,
  OrderStatusResponse,
} from "../api/types";

const TERMINAL_STATUSES = new Set(["completed", "expired", "manual_review", "cancelled"]);

export function useCreateOrder() {
  return useMutation({
    mutationFn: (body: CreateOrderBody) => api.post<CreateOrderResponse>("/orders", body),
  });
}

/** Polls GET /orders/{id} every 3s; stops automatically once in a terminal state. */
export function useOrderStatus(orderId: string | undefined) {
  return useQuery({
    queryKey: ["order", orderId],
    queryFn: ({ signal }) => api.get<OrderStatusResponse>(`/orders/${orderId}`, signal),
    enabled: Boolean(orderId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || TERMINAL_STATUSES.has(data.status)) return false;
      return 3000;
    },
  });
}

export function useCancelOrder(orderId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(`/orders/${orderId}/cancel`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderId] });
    },
  });
}

/** DEV ONLY: simulates a confirmed payment via MockPaymentProvider. */
export function useMockPay(orderId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(`/orders/${orderId}/_mock_pay`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderId] });
    },
  });
}
