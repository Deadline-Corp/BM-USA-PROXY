import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type {
  AccessDetail,
  AccessesResponse,
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

export function useAccessDetail(publicId: string | undefined) {
  return useQuery({
    queryKey: accessDetailQueryKey(publicId),
    queryFn: ({ signal }) => api.get<AccessDetail>(`/accesses/${publicId}`, signal),
    enabled: Boolean(publicId),
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

export function useSwapAccess(publicId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SwapBody) => api.post<SwapResponse>(`/accesses/${publicId}/swap`, body),
    onSuccess: (data) => {
      // Use the server-returned swap_left directly rather than re-deriving it.
      queryClient.setQueryData<AccessDetail | undefined>(accessDetailQueryKey(publicId), (prev) =>
        prev ? { ...prev, swap_left: data.swap_left } : prev,
      );
      queryClient.invalidateQueries({ queryKey: accessDetailQueryKey(publicId) });
      queryClient.invalidateQueries({ queryKey: accessesQueryKey });
    },
  });
}

export function useExtendAccess(publicId: string | undefined) {
  return useMutation({
    mutationFn: (body: ExtendBody) =>
      api.post<CreateOrderResponse>(`/accesses/${publicId}/extend`, body),
  });
}

export function useRequestConfig(publicId: string | undefined) {
  return useMutation({
    mutationFn: (body: ConfigBody) => api.post<ConfigResponse>(`/accesses/${publicId}/config`, body),
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
