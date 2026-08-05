import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  ActiveOrdersResponse,
  CreateOrderBody,
  CreateOrderResponse,
  OrderStatusResponse,
  PaymentMethodsResponse,
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

/** Rails the buyer may pay on. Static per deployment, so cached for the session. */
export function usePaymentMethods() {
  return useQuery({
    queryKey: ["payment-methods"],
    queryFn: ({ signal }) => api.get<PaymentMethodsResponse>("/payment-methods", signal),
    staleTime: Infinity,
  });
}

/**
 * Orders still in flight. Polled while the app is open so a payment made from another
 * device (or after the checkout tab was closed) shows up without a manual refresh.
 */
export function useActiveOrders() {
  return useQuery({
    queryKey: ["orders", "active"],
    queryFn: ({ signal }) => api.get<ActiveOrdersResponse>("/orders", signal),
    refetchInterval: 10_000,
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
