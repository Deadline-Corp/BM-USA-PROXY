import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { poolApi } from "@/shared/api/endpoints";
import type { ConnectionUpdate, ListParams } from "@/shared/api/types";

export function usePoolSummary() {
  return useQuery({
    queryKey: ["pool", "summary"],
    queryFn: poolApi.summary,
    refetchInterval: 60_000,
  });
}

export function useConnections(params: ListParams) {
  return useQuery({
    queryKey: ["connections", params],
    queryFn: () => poolApi.listConnections(params),
  });
}

export function useUpdateConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ConnectionUpdate }) =>
      poolApi.updateConnection(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connections"] });
      qc.invalidateQueries({ queryKey: ["pool", "summary"] });
    },
  });
}

export function useSyncPool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: poolApi.sync,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connections"] });
      qc.invalidateQueries({ queryKey: ["pool", "summary"] });
    },
  });
}
