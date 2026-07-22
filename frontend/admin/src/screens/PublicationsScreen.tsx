import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { DataTable } from "@/shared/components/DataTable";
import { Button } from "@/shared/components/Button";
import { Modal } from "@/shared/components/Modal";
import { Input } from "@/shared/components/form/Input";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { Skeleton } from "@/shared/components/Skeleton";
import { IconPlus } from "@/shared/components/icons";
import { formatDate } from "@/shared/lib/format";
import { useChannels, useCreateChannel, usePosts, usePublishPost } from "@/shared/hooks/usePublications";
import { usePagination } from "@/shared/hooks/usePagination";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Post } from "@/shared/api/types";
import { PostComposer } from "@/screens/publications/PostComposer";

export function PublicationsScreen() {
  const toast = useToast();
  const channelsQuery = useChannels();
  const { limit, offset, setOffset } = usePagination();
  const postsParams = useMemo(() => ({ limit, offset }), [limit, offset]);
  const postsQuery = usePosts(postsParams);
  const publishMutation = usePublishPost();
  const createChannel = useCreateChannel();
  const [composerOpen, setComposerOpen] = useState(false);
  const [channelOpen, setChannelOpen] = useState(false);
  const [chId, setChId] = useState("");
  const [chTitle, setChTitle] = useState("");
  const [chHandle, setChHandle] = useState("");

  async function handleCreateChannel() {
    const tgChatId = Number(chId);
    if (!Number.isFinite(tgChatId) || tgChatId === 0 || !chTitle.trim()) return;
    try {
      await createChannel.mutateAsync({
        tg_chat_id: tgChatId,
        title: chTitle.trim(),
        username: chHandle.trim().replace(/^@/, "") || undefined,
      });
      toast.success("Channel added");
      setChId("");
      setChTitle("");
      setChHandle("");
      setChannelOpen(false);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handlePublish(id: string) {
    try {
      await publishMutation.mutateAsync(id);
      toast.success("Post published");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  const columns = useMemo<ColumnDef<Post, any>[]>(
    () => [
      { header: "Title", accessorKey: "title", cell: ({ row }) => <span className="text-text font-medium">{row.original.title}</span> },
      { header: strings.orders.colStatus, accessorKey: "status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
      { header: strings.publications.views, accessorKey: "views", cell: ({ row }) => <Num value={row.original.views ?? 0} /> },
      { header: strings.publications.clicks, accessorKey: "clicks", cell: ({ row }) => <Num value={row.original.clicks ?? 0} /> },
      {
        header: "Published",
        accessorKey: "published_at",
        cell: ({ row }) => <span className="font-mono text-[.8rem]">{formatDate(row.original.published_at)}</span>,
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) =>
          row.original.status === "draft" ? (
            <Button variant="ghost" size="sm" onClick={() => handlePublish(row.original.id)} isLoading={publishMutation.isPending}>
              {strings.publications.publish}
            </Button>
          ) : null,
      },
    ],
    [publishMutation.isPending],
  );

  return (
    <div>
      <PageHead
        title={strings.publications.title}
        subtitle={strings.publications.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={() => setComposerOpen(true)}>
            <IconPlus />
            {strings.publications.newPost}
          </Button>
        }
      />

      <div className="grid grid-cols-[1fr_2fr] gap-4 max-[1000px]:grid-cols-1">
        <Panel>
          <Panel.Head
            title={strings.publications.channels}
            actions={
              <Button variant="quiet" size="sm" onClick={() => setChannelOpen(true)}>
                <IconPlus className="w-3.5 h-3.5" />
                {strings.publications.newChannel}
              </Button>
            }
          />
          <div className="flex flex-col">
            {channelsQuery.isLoading ? (
              <Skeleton className="h-20 m-4" />
            ) : channelsQuery.isError ? (
              <ErrorState onRetry={() => channelsQuery.refetch()} />
            ) : (channelsQuery.data?.length ?? 0) === 0 ? (
              <EmptyState title="No channels configured" />
            ) : (
              channelsQuery.data?.map((c) => (
                <div key={c.id} className="flex items-center justify-between px-[18px] py-3 border-b border-border last:border-b-0">
                  <div>
                    <div className="text-[.86rem] text-text font-medium">{c.name}</div>
                    <div className="font-mono text-[.76rem] text-text-3">{c.handle}</div>
                  </div>
                  <StatusBadge tone={c.is_active ? "success" : "neutral"} label={c.is_active ? strings.common.active : strings.common.inactive} />
                </div>
              ))
            )}
          </div>
        </Panel>

        <Panel>
          <Panel.Head title={strings.publications.posts} />
          <DataTable
            columns={columns}
            data={postsQuery.data?.items ?? []}
            total={postsQuery.data?.total ?? 0}
            limit={limit}
            offset={offset}
            onOffsetChange={setOffset}
            isLoading={postsQuery.isLoading}
            isError={postsQuery.isError}
            onRetry={postsQuery.refetch}
            getRowId={(row) => row.id}
            emptyTitle="No posts yet"
          />
        </Panel>
      </div>

      <PostComposer open={composerOpen} onClose={() => setComposerOpen(false)} />

      <Modal
        open={channelOpen}
        onClose={() => setChannelOpen(false)}
        title={strings.publications.newChannel}
        footer={
          <>
            <Button variant="ghost" onClick={() => setChannelOpen(false)}>
              {strings.common.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={handleCreateChannel}
              disabled={!chId.trim() || !chTitle.trim()}
              isLoading={createChannel.isPending}
            >
              {strings.common.create}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Telegram chat ID"
            hint="The channel's numeric ID, e.g. -1001234567890. Add the bot as an admin of the channel first."
            value={chId}
            onChange={(e) => setChId(e.target.value)}
            placeholder="-1001234567890"
          />
          <Input label="Title" value={chTitle} onChange={(e) => setChTitle(e.target.value)} />
          <Input
            label="Username (optional)"
            value={chHandle}
            onChange={(e) => setChHandle(e.target.value)}
            placeholder="@channel_handle"
          />
        </div>
      </Modal>
    </div>
  );
}
