import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Me } from "../api/types";

export const meQueryKey = ["me"] as const;

export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: ({ signal }) => api.get<Me>("/me", signal),
  });
}
