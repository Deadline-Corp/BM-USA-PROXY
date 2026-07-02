import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CreateRequestResponse, NewRequestBody, RequestItem } from "../api/types";

export const requestsQueryKey = ["requests"] as const;

export function useRequests() {
  return useQuery({
    queryKey: requestsQueryKey,
    queryFn: ({ signal }) => api.get<RequestItem[]>("/requests", signal),
  });
}

export function useCreateRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NewRequestBody) => api.post<CreateRequestResponse>("/requests", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requestsQueryKey });
    },
  });
}
