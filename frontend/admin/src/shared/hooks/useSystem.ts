import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { systemApi } from "@/shared/api/endpoints";
import type { AdminAccountInput, AppSettings, ListParams, TermsInput } from "@/shared/api/types";

const WELCOME_IMAGE_QUERY_KEY = ["system", "welcome-image"] as const;

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
    mutationFn: (body: TermsInput) => systemApi.putTerms(body),
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

export function useDeleteAdmin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => systemApi.deleteAdmin(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system", "admins"] }),
  });
}

export function useAuditLog(params: ListParams) {
  return useQuery({ queryKey: ["system", "audit", params], queryFn: () => systemApi.audit(params) });
}

/** The bot's /start greeting photo, as a Blob (the endpoint is authenticated, so a plain
 * <img src> can't carry the bearer token — the caller turns this into an object URL).
 * `cacheBust` is a value the caller bumps after every successful upload, folded into both
 * the query key (react-query refetches) and the request URL (the browser can't answer out
 * of its own HTTP cache for "the same" URL either). */
export function useWelcomeImage(cacheBust: number) {
  return useQuery({
    queryKey: [...WELCOME_IMAGE_QUERY_KEY, cacheBust],
    queryFn: () => systemApi.getWelcomeImage(cacheBust),
  });
}

export function useUploadWelcomeImage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => systemApi.uploadWelcomeImage(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: WELCOME_IMAGE_QUERY_KEY }),
  });
}
