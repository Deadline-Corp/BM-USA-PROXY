import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clientsApi } from "@/shared/api/endpoints";
import type { IssueAccessRequest, ListParams } from "@/shared/api/types";

export function useClientsList(params: ListParams) {
  return useQuery({
    queryKey: ["clients", params],
    queryFn: () => clientsApi.list(params),
  });
}

export function useClientDossier(id: string | null) {
  return useQuery({
    queryKey: ["clients", id],
    queryFn: () => clientsApi.get(id as string),
    enabled: id !== null,
  });
}

export function useUpdateClientNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => clientsApi.updateNote(id, note),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["clients", vars.id] });
    },
  });
}

export function useBanClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => clientsApi.ban(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["clients", id] });
    },
  });
}

export function useUnbanClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => clientsApi.unban(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["clients", id] });
    },
  });
}

export function useMessageClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => clientsApi.message(id, text),
    // Refetch the dossier so the operator's reply shows up in the conversation thread.
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["clients", vars.id] });
    },
  });
}

export function useIssueAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: IssueAccessRequest }) => clientsApi.issueAccess(id, body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["clients", vars.id] });
      qc.invalidateQueries({ queryKey: ["accesses"] });
    },
  });
}
