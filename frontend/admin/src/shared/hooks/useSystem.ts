import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { systemApi } from "@/shared/api/endpoints";
import type { AdminAccountInput, AppSettings, ListParams, Terms } from "@/shared/api/types";

export function useAppSettings() {
  return useQuery({ queryKey: ["system", "settings"], queryFn: systemApi.getSettings });
}

export function useUpdateAppSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<AppSettings>) => systemApi.updateSettings(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system", "settings"] }),
  });
}

export function useTerms() {
  return useQuery({ queryKey: ["system", "terms"], queryFn: systemApi.getTerms });
}

export function usePutTerms() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Terms) => systemApi.putTerms(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system", "terms"] }),
  });
}

export function useAdmins() {
  return useQuery({ queryKey: ["system", "admins"], queryFn: systemApi.listAdmins });
}

export function useCreateAdmin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AdminAccountInput) => systemApi.createAdmin(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system", "admins"] }),
  });
}

export function useUpdateAdmin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<AdminAccountInput> }) => systemApi.updateAdmin(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system", "admins"] }),
  });
}

export function useAuditLog(params: ListParams) {
  return useQuery({ queryKey: ["system", "audit", params], queryFn: () => systemApi.audit(params) });
}
