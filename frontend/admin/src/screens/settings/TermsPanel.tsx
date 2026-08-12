import { useEffect, useState } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { IconPlus, IconTrash } from "@/shared/components/icons";
import { useTerms, usePutTerms } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { RequireRole } from "@/shared/auth/RequireRole";
import type { Terms, TermsQuestion } from "@/shared/api/types";

let localIdCounter = 0;
function localId() {
  return `q${++localIdCounter}_${Date.now().toString(36)}`;
}

/** The agreement clients accept before the mini-app lets them buy anything.
 *
 * Three things were wrong here and each one was invisible from the screen:
 *  - the agreement text (`text_md`) had no editor at all, so the only part a customer
 *    actually reads could not be changed from the console;
 *  - Save sent no `text_md`, and the endpoint requires it — every save was a 422 that
 *    surfaced as a red toast and no saved terms;
 *  - questions were sent as `{text}` while the mini-app renders `label`, so a question
 *    added here arrived at the client blank, and saving rewrote the seeded email
 *    question into a shape that lost its format check.
 */
export function TermsPanel() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useTerms();
  const putMutation = usePutTerms();
  const [draft, setDraft] = useState<Terms | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);

  useEffect(() => {
    if (data && !draft) setDraft(data);
  }, [data, draft]);

  function updateQuestion(id: string, patch: Partial<TermsQuestion>) {
    setDraft((prev) =>
      prev
        ? { ...prev, questions: prev.questions.map((q) => (q.id === id ? { ...q, ...patch } : q)) }
        : prev,
    );
  }

  function addQuestion() {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            questions: [
              ...prev.questions,
              { id: localId(), label: "", type: "text", required: true },
            ],
          }
        : prev,
    );
  }

  function removeQuestion(id: string) {
    setDraft((prev) =>
      prev ? { ...prev, questions: prev.questions.filter((q) => q.id !== id) } : prev,
    );
  }

  async function save(publish: boolean) {
    if (!draft) return;
    try {
      const saved = await putMutation.mutateAsync({
        text_md: draft.text_md,
        questions: draft.questions,
        publish,
      });
      setDraft(saved);
      toast.success(
        publish ? `Published — version ${saved.version}, everyone re-accepts` : "Terms saved",
      );
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setConfirmPublish(false);
    }
  }

  return (
    <Panel>
      <Panel.Head
        title={strings.settings.terms}
        subtitle={strings.settings.termsSubtitle}
        actions={
          draft ? (
            // Not "Draft"/"Published": there is no draft state on the server. Whatever is
            // saved here is what the next client to open the app reads. The version is
            // the thing worth showing, because it is what decides who has to accept again.
            <StatusBadge tone={draft.version ? "success" : "warning"} label={draft.version ? `Live · v${draft.version}` : "Not set up"} />
          ) : undefined
        }
      />
      <Panel.Body>
        {isLoading ? (
          <Skeleton className="h-32" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : draft ? (
          <div className="flex flex-col gap-5">
            <RequireRole
              role="owner"
              fallback={
                <Textarea
                  label={strings.settings.termsText}
                  hint={strings.settings.termsTextHint}
                  value={draft.text_md}
                  rows={18}
                  disabled
                />
              }
            >
              <Textarea
                label={strings.settings.termsText}
                hint={strings.settings.termsTextHint}
                value={draft.text_md}
                onChange={(e) => setDraft((prev) => (prev ? { ...prev, text_md: e.target.value } : prev))}
                rows={18}
                placeholder={"## Terms of Service\n\n1. …"}
                className="font-mono text-[.82rem] leading-relaxed"
              />
            </RequireRole>

            <div className="flex flex-col gap-2.5">
              <div>
                <span className="text-[.74rem] uppercase tracking-[.06em] text-text-3 font-semibold">
                  {strings.settings.termsQuestions}
                </span>
                <p className="mt-1 text-[.78rem] text-text-3">{strings.settings.termsQuestionsHint}</p>
              </div>
              {draft.questions.map((q) => (
                <div key={q.id} className="flex items-center gap-2.5 flex-wrap">
                  <Input
                    value={q.label}
                    onChange={(e) => updateQuestion(q.id, { label: e.target.value })}
                    placeholder="Question shown to the client"
                    className="flex-1 min-w-[240px]"
                  />
                  <Select
                    value={q.type}
                    onChange={(e) =>
                      updateQuestion(q.id, { type: e.target.value as TermsQuestion["type"] })
                    }
                    className="w-[140px]"
                  >
                    <option value="text">Free text</option>
                    <option value="email">Email</option>
                  </Select>
                  <Checkbox
                    id={`req-${q.id}`}
                    label="Required"
                    checked={q.required}
                    onChange={(e) => updateQuestion(q.id, { required: e.target.checked })}
                  />
                  <RequireRole role="owner">
                    <Button
                      variant="quiet"
                      size="sm"
                      onClick={() => removeQuestion(q.id)}
                      aria-label="Remove question"
                    >
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
            </div>

            <RequireRole role="owner">
              <div className="flex items-center justify-between gap-3 pt-3 border-t border-border flex-wrap">
                <p className="text-[.78rem] text-text-3 max-w-[620px]">
                  {strings.settings.termsPublishHint}
                </p>
                <div className="flex gap-2 flex-none">
                  <Button variant="ghost" size="sm" onClick={() => save(false)} isLoading={putMutation.isPending}>
                    {strings.common.save}
                  </Button>
                  <Button variant="primary" size="sm" onClick={() => setConfirmPublish(true)}>
                    {strings.settings.publish}
                  </Button>
                </div>
              </div>
            </RequireRole>
          </div>
        ) : null}
      </Panel.Body>

      {/* Publishing is not a save — it puts every existing customer back in front of the
          acceptance screen before they can use the app again. Worth one question. */}
      <ConfirmDialog
        open={confirmPublish}
        onClose={() => setConfirmPublish(false)}
        onConfirm={() => save(true)}
        title={strings.settings.publish}
        description={strings.settings.termsPublishConfirm}
        confirmLabel={strings.settings.publish}
        isSubmitting={putMutation.isPending}
      />
    </Panel>
  );
}
