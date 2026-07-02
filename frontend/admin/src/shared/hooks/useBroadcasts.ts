import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { broadcastsApi } from "@/shared/api/endpoints";
import type { BroadcastInput } from "@/shared/api/types";

export function useBroadcasts() {
  return useQuery({ queryKey: ["broadcasts"], queryFn: broadcastsApi.list });
}

export function useCreateBroadcast() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BroadcastInput) => broadcastsApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts"] }),
  });
}

export function useScheduleBroadcast() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, scheduled_at }: { id: string; scheduled_at: string }) => broadcastsApi.schedule(id, scheduled_at),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts"] }),
  });
}

export function useSendBroadcastNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => broadcastsApi.sendNow(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts"] }),
  });
}

export function useBroadcastProgress(id: string | null) {
  return useQuery({
    queryKey: ["broadcasts", "progress", id],
    queryFn: () => broadcastsApi.progress(id as string),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data?.status === "sending" ? 2000 : false),
  });
}
