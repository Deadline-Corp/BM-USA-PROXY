import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Catalog } from "../api/types";

export const catalogQueryKey = ["catalog"] as const;

export function useCatalog() {
  return useQuery({
    queryKey: catalogQueryKey,
    queryFn: ({ signal }) => api.get<Catalog>("/catalog", signal),
  });
}
