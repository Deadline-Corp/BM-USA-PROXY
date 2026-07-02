import { useState } from "react";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Textarea } from "@/shared/components/form/Textarea";
import { useCreateBroadcast } from "@/shared/hooks/useBroadcasts";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";

interface BroadcastComposerProps {
  open: boolean;
  onClose: () => void;
}

export function BroadcastComposer({ open, onClose }: BroadcastComposerProps) {
  const toast = useToast();
  const createMutation = useCreateBroadcast();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audienceHasActive, setAudienceHasActive] = useState(false);

  function reset() {
    setTitle("");
    setBody("");
    setAudienceHasActive(false);
  }

  async function handleSave() {
    if (!title.trim() || !body.trim()) return;
    try {
      await createMutation.mutateAsync({
        title: title.trim(),
        body: body.trim(),
        audience_filter: audienceHasActive ? { has_active_access: true } : {},
      });
      toast.success("Broadcast created as draft");
      reset();
      onClose();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title={strings.broadcasts.composerTitle}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {strings.common.cancel}
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={!title.trim() || !body.trim()} isLoading={createMutation.isPending}>
            {strings.common.create}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Input label={strings.broadcasts.titleLabel} value={title} onChange={(e) => setTitle(e.target.value)} />
        <Textarea label={strings.broadcasts.bodyLabel} value={body} onChange={(e) => setBody(e.target.value)} rows={5} />
        <label className="flex items-center gap-2 text-[.86rem] text-text-2 cursor-pointer">
          <input
            type="checkbox"
            checked={audienceHasActive}
            onChange={(e) => setAudienceHasActive(e.target.checked)}
            className="w-4 h-4 rounded-[4px] border border-border-2 accent-accent"
          />
          {strings.broadcasts.audienceLabel}: clients with active access only
        </label>
      </div>
    </Modal>
  );
}
