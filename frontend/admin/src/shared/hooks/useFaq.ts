import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { faqApi } from "@/shared/api/endpoints";
import type { FaqItem } from "@/shared/api/types";

export function useFaqList() {
  return useQuery({ queryKey: ["faq"], queryFn: faqApi.list });
}

export function useCreateFaq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Omit<FaqItem, "id">) => faqApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["faq"] }),
  });
}

export function useUpdateFaq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Omit<FaqItem, "id">> }) => faqApi.update(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["faq"] }),
  });
}

export function useDeleteFaq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => faqApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["faq"] }),
  });
}
