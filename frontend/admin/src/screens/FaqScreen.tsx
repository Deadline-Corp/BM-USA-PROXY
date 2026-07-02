import { useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Switch } from "@/shared/components/Switch";
import { Input } from "@/shared/components/form/Input";
import { Textarea } from "@/shared/components/form/Textarea";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { IconEdit, IconPlus, IconTrash } from "@/shared/components/icons";
import { useCreateFaq, useDeleteFaq, useFaqList, useUpdateFaq } from "@/shared/hooks/useFaq";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { FaqItem } from "@/shared/api/types";

export function FaqScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useFaqList();
  const createMutation = useCreateFaq();
  const updateMutation = useUpdateFaq();
  const deleteMutation = useDeleteFaq();

  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<FaqItem | null>(null);

  function startCreate() {
    setEditingId("new");
    setQuestion("");
    setAnswer("");
  }
  function startEdit(item: FaqItem) {
    setEditingId(item.id);
    setQuestion(item.question);
    setAnswer(item.answer);
  }
  function cancelEdit() {
    setEditingId(null);
    setQuestion("");
    setAnswer("");
  }

  async function handleSave() {
    if (!question.trim() || !answer.trim()) return;
    try {
      if (editingId === "new") {
        await createMutation.mutateAsync({ question: question.trim(), answer: answer.trim(), is_published: true });
        toast.success("FAQ item created");
      } else if (editingId) {
        await updateMutation.mutateAsync({ id: editingId, body: { question: question.trim(), answer: answer.trim() } });
        toast.success("FAQ item updated");
      }
      cancelEdit();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleTogglePublished(item: FaqItem) {
    try {
      await updateMutation.mutateAsync({ id: item.id, body: { is_published: !item.is_published } });
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      toast.success("FAQ item deleted");
      setDeleteTarget(null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead
        title={strings.faq.title}
        subtitle={strings.faq.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={startCreate}>
            <IconPlus />
            {strings.faq.add}
          </Button>
        }
      />

      <Panel>
        {isLoading ? (
          <Skeleton className="h-40 m-4" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : (data?.length ?? 0) === 0 && editingId !== "new" ? (
          <EmptyState title="No FAQ items yet" action={<Button variant="ghost" size="sm" onClick={startCreate}>{strings.faq.add}</Button>} />
        ) : (
          <div className="flex flex-col">
            {editingId === "new" && (
              <FaqEditRow
                question={question}
                answer={answer}
                onQuestionChange={setQuestion}
                onAnswerChange={setAnswer}
                onSave={handleSave}
                onCancel={cancelEdit}
                isSaving={createMutation.isPending}
              />
            )}
            {data?.map((item) =>
              editingId === item.id ? (
                <FaqEditRow
                  key={item.id}
                  question={question}
                  answer={answer}
                  onQuestionChange={setQuestion}
                  onAnswerChange={setAnswer}
                  onSave={handleSave}
                  onCancel={cancelEdit}
                  isSaving={updateMutation.isPending}
                />
              ) : (
                <div key={item.id} className="flex items-start gap-3 px-[18px] py-3.5 border-b border-border last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <div className="text-[.88rem] text-text font-medium">{item.question}</div>
                    <div className="text-[.8rem] text-text-2 mt-1 leading-relaxed">{item.answer}</div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <Switch checked={item.is_published} onChange={() => handleTogglePublished(item)} />
                    <Button variant="quiet" size="sm" onClick={() => startEdit(item)} aria-label={strings.common.edit}>
                      <IconEdit />
                    </Button>
                    <Button variant="quiet" size="sm" onClick={() => setDeleteTarget(item)} aria-label={strings.common.delete}>
                      <IconTrash />
                    </Button>
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </Panel>

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title={strings.common.delete}
        description={`Delete "${deleteTarget?.question}"? This cannot be undone.`}
        confirmLabel={strings.common.delete}
        danger
        isSubmitting={deleteMutation.isPending}
      />
    </div>
  );
}

function FaqEditRow({
  question,
  answer,
  onQuestionChange,
  onAnswerChange,
  onSave,
  onCancel,
  isSaving,
}: {
  question: string;
  answer: string;
  onQuestionChange: (v: string) => void;
  onAnswerChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  return (
    <div className="px-[18px] py-4 border-b border-border last:border-b-0 bg-surface-2">
      <div className="flex flex-col gap-3">
        <Input label={strings.faq.question} value={question} onChange={(e) => onQuestionChange(e.target.value)} />
        <Textarea label={strings.faq.answer} value={answer} onChange={(e) => onAnswerChange(e.target.value)} rows={3} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {strings.common.cancel}
          </Button>
          <Button variant="primary" size="sm" onClick={onSave} disabled={!question.trim() || !answer.trim()} isLoading={isSaving}>
            {strings.common.save}
          </Button>
        </div>
      </div>
    </div>
  );
}
