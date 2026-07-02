import { useMemo } from "react";
import clsx from "clsx";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { formatRelative } from "@/shared/lib/format";
import { useGroupedNotificationSettings, useNotificationLog, useUpdateNotificationSetting } from "@/shared/hooks/useNotifications";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { IconMail, IconRefresh, IconTelegram } from "@/shared/components/icons";

export function NotificationsScreen() {
  const toast = useToast();
  const { limit, offset } = usePagination(30);
  const logParams = useMemo(() => ({ limit, offset }), [limit, offset]);
  const logQuery = useNotificationLog(logParams);
  const { groups, isLoading: settingsLoading, isError: settingsError, refetch: refetchSettings } = useGroupedNotificationSettings();
  const updateMutation = useUpdateNotificationSetting();

  async function handleToggle(eventKey: string, channel: "telegram" | "email", current: boolean) {
    try {
      await updateMutation.mutateAsync({ eventKey, body: { [channel]: !current } });
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

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
                  <div key={n.id} className="flex items-center gap-3 px-3.5 py-3 border-b border-border last:border-b-0">
                    <div className="min-w-0 flex-1">
                      <div className="text-[.86rem] text-text font-medium">{n.type}</div>
                      <div className="font-mono text-[.76rem] text-text-3 mt-0.5">{n.user}</div>
                    </div>
                    <span className="text-[.72rem] text-text-3">{formatRelative(n.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>

        {/* Settings matrix */}
        <Panel>
          <Panel.Head title={strings.notifications.settingsTitle} subtitle="Telegram · Email" />
          <Panel.Body>
            {settingsLoading ? (
              <Skeleton className="h-64" />
            ) : settingsError ? (
              <ErrorState onRetry={refetchSettings} />
            ) : groups.length === 0 ? (
              <EmptyState title="No notification events configured" />
            ) : (
              <div className="flex flex-col gap-5">
                {groups.map((group) => (
                  <div key={group.label}>
                    <div className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold mb-2.5">{group.label}</div>
                    <div className="flex flex-col gap-3">
                      {group.items.map((item) => (
                        <div key={item.event_key} className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[.86rem] text-text">{item.label}</div>
                            <div className="text-[.76rem] text-text-3 mt-0.5">{item.description}</div>
                          </div>
                          <div className="flex items-center gap-1.5 flex-none">
                            <ChannelToggle
                              icon={<IconTelegram className="w-3.5 h-3.5" />}
                              label={strings.notifications.telegram}
                              on={item.telegram}
                              onClick={() => handleToggle(item.event_key, "telegram", item.telegram)}
                            />
                            <ChannelToggle
                              icon={<IconMail className="w-3.5 h-3.5" />}
                              label={strings.notifications.email}
                              on={item.email}
                              onClick={() => handleToggle(item.event_key, "email", item.email)}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                <p className="text-[.76rem] text-text-3 pt-1 border-t border-border">
                  Settings save automatically. Telegram bot must be authorized to deliver messages.
                </p>
              </div>
            )}
          </Panel.Body>
        </Panel>
      </div>
    </div>
  );
}

function ChannelToggle({ icon, label, on, onClick }: { icon: React.ReactNode; label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={`${label}: ${on ? "on" : "off"}`}
      className={clsx(
        "flex items-center gap-1.5 h-7 px-2.5 rounded-full border text-[.7rem] font-semibold transition-colors duration-150 ease-brand",
        on ? "bg-accent-soft border-accent-line text-accent" : "bg-surface-2 border-border text-text-3",
      )}
    >
      {icon}
      {label === strings.notifications.telegram ? "TG" : label}
    </button>
  );
}
