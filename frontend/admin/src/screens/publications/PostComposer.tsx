import { useState } from "react";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Textarea } from "@/shared/components/form/Textarea";
import { Select } from "@/shared/components/form/Select";
import { useChannels, useCreatePost } from "@/shared/hooks/usePublications";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";

interface PostComposerProps {
  open: boolean;
  onClose: () => void;
}

export function PostComposer({ open, onClose }: PostComposerProps) {
  const toast = useToast();
  const channelsQuery = useChannels();
  const createMutation = useCreatePost();
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  function reset() {
    setChannelId("");
    setTitle("");
    setBody("");
  }

  async function handleSave() {
    if (!channelId || !title.trim() || !body.trim()) return;
    try {
      await createMutation.mutateAsync({ channel_id: channelId, title: title.trim(), body: body.trim() });
      toast.success("Post created as draft");
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
      title={strings.publications.newPost}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {strings.common.cancel}
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={!channelId || !title.trim() || !body.trim()} isLoading={createMutation.isPending}>
            {strings.common.create}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Select label="Channel" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
          <option value="">Select a channel…</option>
          {channelsQuery.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.handle})
            </option>
          ))}
        </Select>
        <Input label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Textarea label="Body" value={body} onChange={(e) => setBody(e.target.value)} rows={5} />
      </div>
    </Modal>
  );
}
