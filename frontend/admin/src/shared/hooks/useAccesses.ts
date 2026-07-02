import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accessesApi } from "@/shared/api/endpoints";
import type { ListParams } from "@/shared/api/types";

export function useAccessesList(params: ListParams) {
  return useQuery({
    queryKey: ["accesses", params],
    queryFn: () => accessesApi.list(params),
  });
}

export function useRevokeAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => accessesApi.revoke(id, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accesses"] }),
  });
}

export function useExtendAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, minutes }: { id: string; minutes: number }) => accessesApi.extend(id, minutes),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accesses"] }),
  });
}

export function useRotateIp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => accessesApi.rotateIp(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accesses"] }),
  });
}

export function useReissueAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, connectionId }: { id: string; connectionId?: string }) => accessesApi.reissue(id, connectionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accesses"] }),
  });
}
