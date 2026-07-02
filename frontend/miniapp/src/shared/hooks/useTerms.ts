import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AcceptTermsBody, AcceptTermsResponse, Terms } from "../api/types";
import { meQueryKey } from "./useMe";

export const termsQueryKey = ["terms"] as const;

export function useTerms() {
  return useQuery({
    queryKey: termsQueryKey,
    queryFn: ({ signal }) => api.get<Terms>("/terms", signal),
  });
}

export function useAcceptTerms() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AcceptTermsBody) => api.post<AcceptTermsResponse>("/terms/accept", body),
    onSuccess: () => {
      // tos_accepted flips on /me — refetch so guards elsewhere unlock.
      queryClient.invalidateQueries({ queryKey: meQueryKey });
    },
  });
}
