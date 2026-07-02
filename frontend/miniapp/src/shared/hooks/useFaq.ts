import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FaqItem } from "../api/types";

export const faqQueryKey = ["faq"] as const;

export function useFaq() {
  return useQuery({
    queryKey: faqQueryKey,
    queryFn: ({ signal }) => api.get<FaqItem[]>("/faq", signal),
  });
}
