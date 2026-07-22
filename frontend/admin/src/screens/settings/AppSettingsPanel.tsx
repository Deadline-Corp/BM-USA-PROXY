import { useEffect, useState } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import { useAppSettings, useUpdateAppSettings } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { RequireRole } from "@/shared/auth/RequireRole";
import type { AppSettings } from "@/shared/api/types";

/** App settings is a free-form key/value bag per the spec (`GET/PATCH
 * /settings` with no fixed schema given). We render every key as a text
 * input — good enough for an ops console where the shape is whatever the
 * backend currently exposes, and it degrades gracefully as keys are
 * added/removed server-side without a frontend deploy. */
export function AppSettingsPanel() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useAppSettings();
  const updateMutation = useUpdateAppSettings();
  const [draft, setDraft] = useState<AppSettings | null>(null);

  useEffect(() => {
    if (data && !draft) setDraft(data);
  }, [data, draft]);

  const isDirty = draft && data && JSON.stringify(draft) !== JSON.stringify(data);

  // Structured settings (Terms, notification texts) have their own dedicated editors;
  // the generic key/value grid only shows scalar keys, so object values never render
  // as "[object Object]" and the two editors never fight over the same key.
  const isManaged = (key: string) => key.startsWith("notify_texts:") || key === "tos";
  const visibleEntries = Object.entries(draft ?? data ?? {}).filter(
    ([key, value]) => !isManaged(key) && (value === null || typeof value !== "object"),
  );

  async function handleSave() {
    if (!draft || !data) return;
    // Send ONLY the scalar keys that actually changed — the bulk PATCH /settings
    // endpoint rejects keys outside its whitelist (tos / notify_texts have their own).
    const changed: Record<string, unknown> = {};
    for (const [key, value] of visibleEntries) {
      if (value !== (data as Record<string, unknown>)[key]) changed[key] = value;
    }
    try {
      await updateMutation.mutateAsync(changed as Partial<AppSettings>);
      toast.success("Settings saved");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Panel>
      <Panel.Head
        title={strings.settings.appSettings}
        actions={
          <RequireRole role="owner">
            {isDirty && (
              <Button size="sm" variant="primary" onClick={handleSave} isLoading={updateMutation.isPending}>
                {strings.common.save}
              </Button>
            )}
          </RequireRole>
        }
      />
      <Panel.Body>
        {isLoading ? (
          <Skeleton className="h-24" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : visibleEntries.length === 0 ? (
          <EmptyState title="No editable settings" />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              {visibleEntries.map(([key, value]) => (
                <RequireRole
                  key={key}
                  role="owner"
                  fallback={
                    <Input label={key.replace(/_/g, " ")} value={String(value)} disabled />
                  }
                >
                  <Input
                    label={key.replace(/_/g, " ")}
                    value={String(value)}
                    onChange={(e) => setDraft((prev) => ({ ...(prev ?? data), [key]: e.target.value }))}
                  />
                </RequireRole>
              ))}
            </div>
            <p className="mt-4 text-[.78rem] text-text-3">
              Terms of Service and notification message texts are edited on their own
              screens — see the Terms of service panel below and the Notifications page.
            </p>
          </>
        )}
      </Panel.Body>
    </Panel>
  );
}
