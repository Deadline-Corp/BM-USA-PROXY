import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { activeOrdersQueryKey } from "./useOrder";
import { requestsQueryKey } from "./useRequests";
import type {
  AccessDetail,
  AccessesResponse,
  AutoRotateBody,
  ConfigBody,
  ConfigResponse,
  CreateOrderResponse,
  ExtendBody,
  SwapBody,
  SwapResponse,
} from "../api/types";

export const accessesQueryKey = ["accesses"] as const;

export function useAccesses() {
  return useQuery({
    queryKey: accessesQueryKey,
    queryFn: ({ signal }) => api.get<AccessesResponse>("/accesses", signal),
  });
}

export function accessDetailQueryKey(publicId: string | undefined) {
  return ["access", publicId] as const;
}

/** A rotation reboots the phone; the new address takes a few seconds to appear. Asking
 *  the instant it is due reads the old one back and looks like nothing happened. */
const ROTATION_SETTLE_MS = 8_000;
/** Cadence while a rotation is due but the new address has not shown up yet. The sweep
 *  runs once a minute, so this is a short window, not a standing poll. */
const ROTATION_CONFIRM_MS = 6_000;

/**
 * How long to wait before asking for this access again.
 *
 * Exported so the rule can be exercised on its own: it decides whether a customer sees the
 * address they were given or the one they had, and the failure is silent — a screen that
 * refreshes at the wrong moment looks exactly like a screen that is up to date.
 *
 * `override` wins when the caller is driving (a manual rotation is polling at its own
 * pace). `false` from a caller means "no polling"; `undefined` means "you decide".
 */
export function rotationRefetchDelay(
  nextRotationAt: string | null,
  override?: number | false,
): number | false {
  if (override !== undefined) return override;
  if (!nextRotationAt) return false;
  const wait = new Date(nextRotationAt).getTime() + ROTATION_SETTLE_MS - Date.now();
  // Overdue: the sweep has not run yet, or the phone is still coming back up. Check again
  // shortly. Each answer carries a fresh due time, so this ends by itself the moment the
  // rotation lands.
  return wait > 0 ? wait : ROTATION_CONFIRM_MS;
}

export function useAccessDetail(
  publicId: string | undefined,
  options?: { refetchInterval?: number | false },
) {
  return useQuery({
    queryKey: accessDetailQueryKey(publicId),
    queryFn: ({ signal }) => api.get<AccessDetail>(`/accesses/${publicId}`, signal),
    enabled: Boolean(publicId),
    // Auto-rotation changes the address on the server with nothing to tell the screen, so
    // a customer watching this page kept seeing the address they already had — which is
    // how a working feature got reported as broken. Rather than poll blindly, wait for the
    // moment the server says the next change is due: one request per rotation instead of
    // one every few seconds for an interval that may be an hour long.
    refetchInterval: (query) =>
      rotationRefetchDelay(query.state.data?.next_rotation_at ?? null, options?.refetchInterval),
    // The interval above only fires while the tab is in front. A mini app spends most of
    // its life backgrounded, and coming back to a stale address is the same complaint.
    refetchOnWindowFocus: true,
  });
}

/** Rotate-IP mutation. On 429, the caller reads `error.headers.get('Retry-After')`. */
export function useRotateIp(publicId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(`/accesses/${publicId}/rotate-ip`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: accessDetailQueryKey(publicId) });
      queryClient.invalidateQueries({ queryKey: accessesQueryKey });
    },
    // Swallow 429 here — callers use isError + error to drive the cooldown UI directly.
    retry: false,
  });
}

/** Turn scheduled rotation on (with an interval, in minutes) or off. */
export function useSetAutoRotate(publicId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AutoRotateBody) =>
      api.put<{ auto_rotate_minutes: number | null }>(`/accesses/${publicId}/auto-rotate`, body),
    onSuccess: (data) => {
      queryClient.setQueryData<AccessDetail | undefined>(accessDetailQueryKey(publicId), (prev) =>
        prev ? { ...prev, auto_rotate_minutes: data.auto_rotate_minutes } : prev,
      );
      queryClient.invalidateQueries({ queryKey: accessesQueryKey });
    },
  });
}

export function useSwapAccess(publicId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SwapBody) => api.post<SwapResponse>(`/accesses/${publicId}/swap`, body),
    onSuccess: (data) => {
      // Use the server-returned unlock time directly rather than re-deriving it: the
      // cooldown's length is the backend's rule, and a second copy of it here would be a
      // second answer to "when can I swap again".
      queryClient.setQueryData<AccessDetail | undefined>(accessDetailQueryKey(publicId), (prev) =>
        prev ? { ...prev, swap_available_at: data.swap_available_at } : prev,
      );
      queryClient.invalidateQueries({ queryKey: accessDetailQueryKey(publicId) });
      queryClient.invalidateQueries({ queryKey: accessesQueryKey });
    },
  });
}

export function useExtendAccess(publicId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExtendBody) =>
      api.post<CreateOrderResponse>(`/accesses/${publicId}/extend`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: activeOrdersQueryKey });
      queryClient.invalidateQueries({ queryKey: accessesQueryKey });
      queryClient.invalidateQueries({ queryKey: accessDetailQueryKey(publicId) });
    },
  });
}

export function useRequestConfig(publicId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConfigBody) => api.post<ConfigResponse>(`/accesses/${publicId}/config`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requestsQueryKey });
    },
  });
}

export function isRetryAfterError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 429;
}

export function getRetryAfterSeconds(error: ApiError): number {
  const header = error.headers.get("Retry-After");
  const parsed = header ? Number.parseInt(header, 10) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 60;
}
