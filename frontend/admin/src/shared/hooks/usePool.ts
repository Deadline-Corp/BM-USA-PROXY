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

/** Cities with at least one phone — the city picker when issuing an access. */
export function usePoolLocations() {
  return useQuery({
    queryKey: ["pool", "locations"],
    queryFn: poolApi.locations,
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

/** Send a reboot to one phone.
 *
 *  Invalidates nothing: the device drops off the network for a minute or two, so the pool
 *  list refetching right now would only paint it offline before it has had a chance to
 *  come back. The next scheduled refresh reports what actually happened. */
export function useRebootConnection() {
  return useMutation({
    mutationFn: (id: string) => poolApi.reboot(id),
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
