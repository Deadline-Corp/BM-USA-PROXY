import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { requestsApi } from "@/shared/api/endpoints";
import type { RequestStatus, SupportRequest } from "@/shared/api/types";

export function useRequestsList(status?: string) {
  return useQuery({
    queryKey: ["requests", status],
    queryFn: () => requestsApi.list(status),
  });
}

export function useUpdateRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Pick<SupportRequest, "status" | "assignee_id">> }) =>
      requestsApi.update(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["requests"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useAddRequestComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) => requestsApi.addComment(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["requests"] }),
  });
}

export const REQUEST_STATUSES: RequestStatus[] = ["new", "in_progress", "waiting", "done"];
