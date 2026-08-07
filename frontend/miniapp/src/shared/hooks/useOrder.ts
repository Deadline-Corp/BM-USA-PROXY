import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { accessesQueryKey } from "./useAccesses";
import type {
  ActiveOrdersResponse,
  CreateOrderBody,
  CreateOrderResponse,
  OrderStatusResponse,
  PaymentMethodsResponse,
} from "../api/types";

const TERMINAL_STATUSES = new Set(["completed", "expired", "manual_review", "cancelled"]);

/** The "Your orders" strip on Home. */
export const activeOrdersQueryKey = ["orders", "active"] as const;

/**
 * Refresh everything an order leaving `awaiting_payment` changes.
 *
 * The app sets a global `staleTime` of 15s, so a screen the buyer returns to inside that
 * window renders from cache without asking the server. That is right for browsing and
 * wrong after an action: cancel an invoice, walk back to Home, and the dead order was
 * still sitting there counting down as if it were live. Anything that ends an order has
 * to say so explicitly rather than wait for a poll to notice.
 */
function invalidateOrderViews(qc: QueryClient, orderId: string | undefined) {
  qc.invalidateQueries({ queryKey: ["order", orderId] });
  qc.invalidateQueries({ queryKey: activeOrdersQueryKey });
  // A completed order becomes an access — the Home hero and the Access tab both read it.
  qc.invalidateQueries({ queryKey: accessesQueryKey });
}

export function useCreateOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateOrderBody) => api.post<CreateOrderResponse>("/orders", body),
    // A brand-new order belongs on Home immediately, for the same reason a cancelled one
    // has to leave it immediately.
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: activeOrdersQueryKey });
    },
  });
}

/** Polls GET /orders/{id} every 3s; stops automatically once in a terminal state. */
export function useOrderStatus(orderId: string | undefined) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["order", orderId],
    queryFn: ({ signal }) => api.get<OrderStatusResponse>(`/orders/${orderId}`, signal),
    enabled: Boolean(orderId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || TERMINAL_STATUSES.has(data.status)) return false;
      return 3000;
    },
  });

  // An order can also finish without the buyer touching anything — it gets paid, or the
  // invoice times out. The poll above sees that; the rest of the app would not until its
  // own cache went stale, leaving Home advertising an order that is over.
  const status = query.data?.status;
  useEffect(() => {
    if (status && TERMINAL_STATUSES.has(status)) {
      queryClient.invalidateQueries({ queryKey: activeOrdersQueryKey });
      queryClient.invalidateQueries({ queryKey: accessesQueryKey });
    }
  }, [status, queryClient]);

  return query;
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
    queryKey: activeOrdersQueryKey,
    queryFn: ({ signal }) => api.get<ActiveOrdersResponse>("/orders", signal),
    refetchInterval: 10_000,
  });
}

export function useCancelOrder(orderId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(`/orders/${orderId}/cancel`),
    onSuccess: () => invalidateOrderViews(queryClient, orderId),
  });
}

/** DEV ONLY: simulates a confirmed payment via MockPaymentProvider. */
export function useMockPay(orderId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(`/orders/${orderId}/_mock_pay`),
    onSuccess: () => invalidateOrderViews(queryClient, orderId),
  });
}
