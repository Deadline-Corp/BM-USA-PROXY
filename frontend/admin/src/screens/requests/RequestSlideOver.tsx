import { useState } from "react";
import { SlideOver } from "@/shared/components/SlideOver";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Skeleton } from "@/shared/components/Skeleton";
import { Textarea } from "@/shared/components/form/Textarea";
import { formatDateTime } from "@/shared/lib/format";
import { useAddRequestComment, useRequestDetail } from "@/shared/hooks/useRequests";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { SupportRequest } from "@/shared/api/types";

interface RequestSlideOverProps {
  request: SupportRequest | null;
  onClose: () => void;
}

export function RequestSlideOver({ request, onClose }: RequestSlideOverProps) {
  const toast = useToast();
  const commentMutation = useAddRequestComment();
  const detailQuery = useRequestDetail(request?.id ?? null);
  const detail = detailQuery.data;
  const [comment, setComment] = useState("");

  async function handleAddComment() {
    if (!request || !comment.trim()) return;
    try {
      await commentMutation.mutateAsync({ id: request.id, body: comment.trim() });
      toast.success("Comment added");
      setComment("");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <SlideOver
      open={request !== null}
      onClose={onClose}
      title={request?.subject ?? "Request"}
      subtitle={request ? `${request.user} · ${formatDateTime(request.created_at)}` : undefined}
    >
      {request && (
        <div className="flex flex-col gap-5">
          <StatusBadge status={request.status} />

          {detail?.body ? (
            <div>
              <div className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold mb-2">
                Message
              </div>
              <p className="whitespace-pre-wrap text-[.86rem] leading-relaxed text-text border border-border rounded-lg px-3.5 py-3 bg-surface">
                {detail.body}
              </p>
            </div>
          ) : null}

          <div>
            <div className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold mb-2">
              {strings.requests.comments}
            </div>
            {detailQuery.isLoading ? (
              <Skeleton className="h-16" />
            ) : (detail?.comments.length ?? 0) === 0 ? (
              <div className="text-[.82rem] text-text-3 border border-dashed border-border rounded-lg px-3.5 py-3">
                No comments yet.
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {detail?.comments.map((c) => (
                  <div key={c.id} className="border border-border rounded-lg px-3 py-2 bg-surface">
                    <p className="whitespace-pre-wrap text-[.84rem] text-text">{c.body}</p>
                    <div className="text-[.7rem] text-text-3 mt-1">
                      {c.author} · {formatDateTime(c.created_at)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <Textarea
              label={strings.requests.addComment}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={strings.requests.commentPlaceholder}
              rows={3}
            />
            <div className="flex justify-end mt-2">
              <Button
                size="sm"
                variant="primary"
                onClick={handleAddComment}
                disabled={!comment.trim()}
                isLoading={commentMutation.isPending}
              >
                {strings.requests.addComment}
              </Button>
            </div>
          </div>
        </div>
      )}
    </SlideOver>
  );
}
