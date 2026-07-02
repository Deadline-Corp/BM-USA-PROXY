import { useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { TableSkeleton } from "@/shared/components/Skeleton";
import { IconPlus } from "@/shared/components/icons";
import { useBroadcastProgress, useBroadcasts, useSendBroadcastNow } from "@/shared/hooks/useBroadcasts";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { BroadcastComposer } from "@/screens/broadcasts/BroadcastComposer";

export function BroadcastsScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useBroadcasts();
  const sendMutation = useSendBroadcastNow();
  const [composerOpen, setComposerOpen] = useState(false);
  const [progressId, setProgressId] = useState<string | null>(null);
  const progressQuery = useBroadcastProgress(progressId);

  async function handleSendNow(id: string) {
    try {
      await sendMutation.mutateAsync(id);
      toast.success("Broadcast sending");
      setProgressId(id);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead
        title={strings.broadcasts.title}
        subtitle={strings.broadcasts.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={() => setComposerOpen(true)}>
            <IconPlus />
            {strings.broadcasts.create}
          </Button>
        }
      />

      <Panel>
        {isLoading ? (
          <TableSkeleton cols={4} />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState title="No broadcasts yet" action={<Button variant="ghost" size="sm" onClick={() => setComposerOpen(true)}>{strings.broadcasts.create}</Button>} />
        ) : (
          <div className="flex flex-col">
            {data?.items.map((b) => (
              <div key={b.id} className="flex items-center gap-3 px-[18px] py-3.5 border-b border-border last:border-b-0">
                <div className="min-w-0 flex-1">
                  <div className="text-[.88rem] text-text font-medium truncate">{b.title}</div>
                  <div className="text-[.78rem] text-text-3 mt-0.5 truncate">{b.body}</div>
                  {progressId === b.id && progressQuery.data && (
                    <div className="mt-2 flex items-center gap-2">
                      <div className="h-1 w-32 bg-surface-2 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-accent rounded-full transition-[width] duration-300 ease-brand"
                          style={{ width: `${progressQuery.data.total > 0 ? Math.round((progressQuery.data.delivered / progressQuery.data.total) * 100) : 0}%` }}
                        />
                      </div>
                      <span className="font-mono tabular-nums text-[.72rem] text-text-3">
                        {progressQuery.data.delivered}/{progressQuery.data.total}
                      </span>
                    </div>
                  )}
                </div>
                <StatusBadge status={b.status} />
                {b.status === "draft" && (
                  <Button variant="ghost" size="sm" onClick={() => handleSendNow(b.id)} isLoading={sendMutation.isPending}>
                    {strings.broadcasts.sendNow}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>

      <BroadcastComposer open={composerOpen} onClose={() => setComposerOpen(false)} />
    </div>
  );
}
