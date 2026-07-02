import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "@/shared/api/endpoints";
import type { ListParams, NotificationSettingEntry } from "@/shared/api/types";

export function useNotificationLog(params: ListParams) {
  return useQuery({ queryKey: ["notifications", "log", params], queryFn: () => notificationsApi.log(params) });
}

export function useNotificationSettings() {
  return useQuery({ queryKey: ["notifications", "settings"], queryFn: notificationsApi.getSettings });
}

export function useUpdateNotificationSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ eventKey, body }: { eventKey: string; body: Partial<Pick<NotificationSettingEntry, "telegram" | "email">> }) =>
      notificationsApi.updateSettings(eventKey, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications", "settings"] }),
  });
}

/** Groups the flat settings list into categories by a simple key-prefix
 * heuristic (payment_*, payout_*, everything else = infrastructure), since
 * the API surface doesn't define an explicit category field. Falls back to
 * a single "Events" group if prefixes don't match the expected pattern. */
export function useGroupedNotificationSettings() {
  const query = useNotificationSettings();
  const groups = useMemo(() => {
    const items = query.data ?? [];
    const payment = items.filter((i) => i.event_key.startsWith("payment"));
    const payout = items.filter((i) => i.event_key.startsWith("payout"));
    const rest = items.filter((i) => !i.event_key.startsWith("payment") && !i.event_key.startsWith("payout"));
    const result: { label: string; items: NotificationSettingEntry[] }[] = [];
    if (payment.length) result.push({ label: "Payment events", items: payment });
    if (payout.length) result.push({ label: "Payout events", items: payout });
    if (rest.length) result.push({ label: payment.length || payout.length ? "Infrastructure events" : "Events", items: rest });
    return result;
  }, [query.data]);
  return { ...query, groups };
}
