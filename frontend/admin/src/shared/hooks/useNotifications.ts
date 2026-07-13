import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "@/shared/api/endpoints";
import type { ListParams } from "@/shared/api/types";

export function useNotificationLog(params: ListParams) {
  return useQuery({ queryKey: ["notifications", "log", params], queryFn: () => notificationsApi.log(params) });
}

/** Notification message templates: a `{ template_code: custom_text }` map. */
export function useNotificationSettings() {
  return useQuery({ queryKey: ["notifications", "settings"], queryFn: notificationsApi.getSettings });
}

export function useUpdateNotificationTexts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (texts: Record<string, string>) => notificationsApi.updateTexts(texts),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications", "settings"] }),
  });
}
