import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clientsApi } from "@/shared/api/endpoints";
import type { IssueAccessRequest, ListParams } from "@/shared/api/types";

export function useClientsList(params: ListParams) {
  return useQuery({
    queryKey: ["clients", params],
    queryFn: () => clientsApi.list(params),
    // Safety net for changes NOT driven by this operator (a client buys/trials via
    // the bot, or another operator acts): refresh when the admin tab regains focus.
    refetchOnWindowFocus: true,
  });
}

export function useClientDossier(id: string | null) {
  return useQuery({
    queryKey: ["clients", id],
    queryFn: () => clientsApi.get(id as string),
    enabled: id !== null,
    // The dossier carries the conversation, and the other side of that conversation is a
    // person typing into the bot right now. Nothing the operator does triggers a refetch,
    // so without polling an incoming message only appeared after closing and reopening the
    // panel — which reads as "the client has not replied yet" while the reply is sitting
    // on the server. Ten seconds is well inside the pause between two chat messages.
    // The query is disabled with the panel shut (id === null), so this costs nothing when
    // no dossier is open.
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
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

export function useRefreshTelegram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => clientsApi.refreshTelegram(id),
    onSuccess: () => {
      // Both the dossier header and the row in the list render the handle.
      qc.invalidateQueries({ queryKey: ["clients"] });
    },
  });
}

export function useIssueAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: IssueAccessRequest }) => clientsApi.issueAccess(id, body),
    onSuccess: () => {
      // Prefix-invalidate the whole "clients" tree so BOTH the list
      // (["clients", params]) and the open dossier (["clients", id]) refetch —
      // issuing access flips the client's ACCESS column in the list.
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["accesses"] });
    },
  });
}
