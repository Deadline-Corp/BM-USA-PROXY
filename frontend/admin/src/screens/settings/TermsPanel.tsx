import { useEffect, useState } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { IconPlus, IconTrash } from "@/shared/components/icons";
import { useTerms, usePutTerms } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { RequireRole } from "@/shared/auth/RequireRole";
import type { Terms, TermsQuestion } from "@/shared/api/types";

let localIdCounter = 0;
function localId() {
  return `local-${++localIdCounter}`;
}

export function TermsPanel() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useTerms();
  const putMutation = usePutTerms();
  const [draft, setDraft] = useState<Terms | null>(null);

  useEffect(() => {
    if (data && !draft) setDraft(data);
  }, [data, draft]);

  function updateQuestion(id: string, patch: Partial<TermsQuestion>) {
    setDraft((prev) => (prev ? { ...prev, questions: prev.questions.map((q) => (q.id === id ? { ...q, ...patch } : q)) } : prev));
  }

  function addQuestion() {
    setDraft((prev) =>
      prev ? { ...prev, questions: [...prev.questions, { id: localId(), text: "", required: true }] } : prev,
    );
  }

  function removeQuestion(id: string) {
    setDraft((prev) => (prev ? { ...prev, questions: prev.questions.filter((q) => q.id !== id) } : prev));
  }

  async function handleSave(publish?: boolean) {
    if (!draft) return;
    try {
      await putMutation.mutateAsync({ ...draft, published: publish ?? draft.published });
      toast.success(publish ? "Terms published" : "Terms saved");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Panel>
      <Panel.Head
        title={strings.settings.terms}
        subtitle={draft ? `Version ${draft.version}` : undefined}
        actions={
          data && (
            <StatusBadge tone={data.published ? "success" : "neutral"} label={data.published ? "Published" : "Draft"} />
          )
        }
      />
      <Panel.Body>
        {isLoading ? (
          <Skeleton className="h-32" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : draft ? (
          <div className="flex flex-col gap-3">
            {draft.questions.map((q) => (
              <div key={q.id} className="flex items-center gap-2.5">
                <Input
                  value={q.text}
                  onChange={(e) => updateQuestion(q.id, { text: e.target.value })}
                  placeholder="Question text"
                  className="flex-1"
                  disabled={false}
                />
                <Checkbox
                  id={`req-${q.id}`}
                  label="Required"
                  checked={q.required}
                  onChange={(e) => updateQuestion(q.id, { required: e.target.checked })}
                />
                <RequireRole role="owner">
                  <Button variant="quiet" size="sm" onClick={() => removeQuestion(q.id)} aria-label="Remove question">
                    <IconTrash className="w-3.5 h-3.5" />
                  </Button>
                </RequireRole>
              </div>
            ))}

            <RequireRole role="owner">
              <div>
                <Button variant="quiet" size="sm" onClick={addQuestion}>
                  <IconPlus className="w-3.5 h-3.5" />
                  {strings.settings.addQuestion}
                </Button>
              </div>
            </RequireRole>

            <RequireRole role="owner">
              <div className="flex justify-end gap-2 pt-2 border-t border-border">
                <Button variant="ghost" size="sm" onClick={() => handleSave()} isLoading={putMutation.isPending}>
                  {strings.common.save}
                </Button>
                <Button variant="primary" size="sm" onClick={() => handleSave(true)} isLoading={putMutation.isPending}>
                  {strings.settings.publish}
                </Button>
              </div>
            </RequireRole>
          </div>
        ) : null}
      </Panel.Body>
    </Panel>
  );
}
