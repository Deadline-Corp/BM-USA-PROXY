import { useState } from "react";
import { SlideOver } from "@/shared/components/SlideOver";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Textarea } from "@/shared/components/form/Textarea";
import { formatDateTime } from "@/shared/lib/format";
import { useAddRequestComment } from "@/shared/hooks/useRequests";
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

          <div>
            <div className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold mb-2">
              {strings.requests.comments}
            </div>
            <div className="text-[.82rem] text-text-3 border border-dashed border-border rounded-lg px-3.5 py-3">
              Comments load from the request thread once the backend returns them inline.
            </div>
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
