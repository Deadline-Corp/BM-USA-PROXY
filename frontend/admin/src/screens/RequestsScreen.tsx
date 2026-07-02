import { useMemo, useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { formatRelative } from "@/shared/lib/format";
import { REQUEST_STATUSES, useRequestsList, useUpdateRequest } from "@/shared/hooks/useRequests";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { RequestStatus, SupportRequest } from "@/shared/api/types";
import { RequestSlideOver } from "@/screens/requests/RequestSlideOver";
import { IconChevronLeft, IconChevronRight } from "@/shared/components/icons";

const COLUMN_LABEL: Record<RequestStatus, string> = {
  new: strings.requests.colNew,
  in_progress: strings.requests.colInProgress,
  waiting: strings.requests.colWaiting,
  done: strings.requests.colDone,
};

export function RequestsScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useRequestsList();
  const updateMutation = useUpdateRequest();
  const [selected, setSelected] = useState<SupportRequest | null>(null);

  const columns = useMemo(() => {
    const grouped: Record<RequestStatus, SupportRequest[]> = { new: [], in_progress: [], waiting: [], done: [] };
    for (const r of data?.items ?? []) {
      if (r.status in grouped) grouped[r.status as RequestStatus].push(r);
    }
    return grouped;
  }, [data]);

  async function moveStatus(request: SupportRequest, direction: 1 | -1) {
    const idx = REQUEST_STATUSES.indexOf(request.status);
    const nextIdx = idx + direction;
    if (nextIdx < 0 || nextIdx >= REQUEST_STATUSES.length) return;
    try {
      await updateMutation.mutateAsync({ id: request.id, body: { status: REQUEST_STATUSES[nextIdx] } });
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead title={strings.requests.title} subtitle={strings.requests.subtitle} />

      {isLoading ? (
        <div className="grid grid-cols-4 gap-4 max-[900px]:grid-cols-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[400px] rounded-lg" />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div className="grid grid-cols-4 gap-4 items-start max-[900px]:grid-cols-1">
          {REQUEST_STATUSES.map((status) => (
            <div key={status} className="bg-surface-2 border border-border rounded-lg flex flex-col max-h-[calc(100vh-220px)]">
              <div className="flex items-center justify-between px-3.5 py-3 border-b border-border flex-none">
                <span className="text-[.82rem] font-semibold text-text">{COLUMN_LABEL[status]}</span>
                <span className="font-mono tabular-nums text-[.74rem] text-text-3 bg-surface border border-border rounded-full px-2 py-0.5">
                  {columns[status].length}
                </span>
              </div>
              <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-2">
                {columns[status].length === 0 ? (
                  <div className="text-[.78rem] text-text-3 text-center py-6">Empty</div>
                ) : (
                  columns[status].map((r) => (
                    <div
                      key={r.id}
                      className="bg-surface border border-border rounded-lg p-3 cursor-pointer hover:border-border-2 transition-colors duration-150 ease-brand"
                      onClick={() => setSelected(r)}
                    >
                      <div className="text-[.84rem] text-text font-medium leading-snug mb-1">{r.subject}</div>
                      <div className="font-mono text-[.74rem] text-text-3 mb-2">{r.user}</div>
                      <div className="flex items-center justify-between">
                        <span className="text-[.7rem] text-text-3">{formatRelative(r.created_at)}</span>
                        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            disabled={REQUEST_STATUSES.indexOf(status) === 0}
                            onClick={() => moveStatus(r, -1)}
                            className="w-6 h-6 grid place-items-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text disabled:opacity-30 disabled:pointer-events-none transition-colors duration-150 ease-brand"
                            aria-label="Move back"
                          >
                            <IconChevronLeft className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={REQUEST_STATUSES.indexOf(status) === REQUEST_STATUSES.length - 1}
                            onClick={() => moveStatus(r, 1)}
                            className="w-6 h-6 grid place-items-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text disabled:opacity-30 disabled:pointer-events-none transition-colors duration-150 ease-brand"
                            aria-label="Move forward"
                          >
                            <IconChevronRight className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) === 0 && <EmptyState title="No requests" />}

      <RequestSlideOver request={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
