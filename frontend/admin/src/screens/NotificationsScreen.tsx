import { useEffect, useMemo, useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { formatRelative } from "@/shared/lib/format";
import {
  useNotificationLog,
  useNotificationSettings,
  useUpdateNotificationTexts,
} from "@/shared/hooks/useNotifications";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { IconRefresh } from "@/shared/components/icons";

function humanize(code: string): string {
  return code.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function NotificationsScreen() {
  const toast = useToast();
  const { limit, offset } = usePagination(30);
  const logParams = useMemo(() => ({ limit, offset }), [limit, offset]);
  const logQuery = useNotificationLog(logParams);
  const settingsQuery = useNotificationSettings();
  const updateTexts = useUpdateNotificationTexts();

  const [drafts, setDrafts] = useState<Record<string, string>>({});
  useEffect(() => {
    if (settingsQuery.data) setDrafts(settingsQuery.data);
  }, [settingsQuery.data]);

  const dirty = useMemo(() => {
    const server = settingsQuery.data ?? {};
    return Object.keys(drafts).some((k) => (drafts[k] ?? "") !== (server[k] ?? ""));
  }, [drafts, settingsQuery.data]);

  async function handleSave() {
    // Persist only the codes the operator actually changed — untouched ones keep
    // falling back to their built-in defaults instead of being frozen as overrides.
    const server = settingsQuery.data ?? {};
    const changed = Object.fromEntries(
      Object.entries(drafts).filter(([code, value]) => (value ?? "") !== (server[code] ?? "")),
    );
    try {
      await updateTexts.mutateAsync(changed);
      toast.success(strings.notifications.settingsSaved);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  const codes = Object.keys(settingsQuery.data ?? {});

  return (
    <div>
      <PageHead
        title={strings.notifications.title}
        subtitle={strings.notifications.subtitle}
        actions={
          <Button variant="ghost" size="sm" onClick={() => logQuery.refetch()}>
            <IconRefresh />
            {strings.common.refresh}
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-4 max-[1000px]:grid-cols-1">
        {/* Event log */}
        <Panel>
          <Panel.Head title={strings.notifications.eventLog} subtitle="Newest first" />
          <div className="p-1.5">
            {logQuery.isLoading ? (
              <Skeleton className="h-64 m-3" />
            ) : logQuery.isError ? (
              <ErrorState onRetry={() => logQuery.refetch()} />
            ) : (logQuery.data?.items.length ?? 0) === 0 ? (
              <EmptyState title="No notifications yet" />
            ) : (
              <div className="flex flex-col">
                {logQuery.data?.items.map((n) => (
                  <div
                    key={n.id}
                    className="flex items-center gap-3 px-3.5 py-3 border-b border-border last:border-b-0"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-[.86rem] text-text font-medium">{humanize(n.type)}</div>
                      <div className="font-mono text-[.76rem] text-text-3 mt-0.5">{n.user}</div>
                    </div>
                    <span className="text-[.72rem] text-text-3">{formatRelative(n.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>

        {/* Message templates editor */}
        <Panel>
          <Panel.Head title={strings.notifications.settingsTitle} subtitle={strings.notifications.settingsSubtitle} />
          <Panel.Body>
            {settingsQuery.isLoading ? (
              <Skeleton className="h-64" />
            ) : settingsQuery.isError ? (
              <ErrorState onRetry={() => settingsQuery.refetch()} />
            ) : codes.length === 0 ? (
              <EmptyState title="No templates configured" />
            ) : (
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-4 max-h-[calc(100vh-320px)] overflow-y-auto pr-1">
                  {codes.map((code) => (
                    <div key={code}>
                      <label className="block text-[.84rem] text-text font-medium">{humanize(code)}</label>
                      <div className="font-mono text-[.68rem] text-text-3 mt-0.5 mb-1.5">{code}</div>
                      <textarea
                        value={drafts[code] ?? ""}
                        onChange={(e) => setDrafts((d) => ({ ...d, [code]: e.target.value }))}
                        placeholder={strings.notifications.settingsPlaceholder}
                        rows={2}
                        className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-[.84rem] text-text placeholder:text-text-3 focus:outline-none focus:border-accent-line resize-y"
                      />
                    </div>
                  ))}
                </div>
                <div className="flex items-center justify-end pt-1 border-t border-border">
                  <Button variant="primary" size="sm" disabled={!dirty || updateTexts.isPending} onClick={handleSave}>
                    {updateTexts.isPending ? strings.common.saving : strings.common.save}
                  </Button>
                </div>
              </div>
            )}
          </Panel.Body>
        </Panel>
      </div>
    </div>
  );
}
