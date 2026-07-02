import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { publicationsApi } from "@/shared/api/endpoints";
import type { ListParams, Post } from "@/shared/api/types";

export function useChannels() {
  return useQuery({ queryKey: ["channels"], queryFn: publicationsApi.listChannels });
}

export function useCreateChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; handle: string; is_active: boolean }) => publicationsApi.createChannel(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }),
  });
}

export function usePosts(params: ListParams) {
  return useQuery({ queryKey: ["posts", params], queryFn: () => publicationsApi.listPosts(params) });
}

export function useCreatePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Omit<Post, "id" | "status" | "published_at" | "views" | "clicks">) => publicationsApi.createPost(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["posts"] }),
  });
}

export function usePublishPost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => publicationsApi.publishPost(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["posts"] }),
  });
}
