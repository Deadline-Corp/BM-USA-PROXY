import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tariffsApi } from "@/shared/api/endpoints";
import type { TariffInput } from "@/shared/api/types";

export function useTariffs() {
  return useQuery({
    queryKey: ["tariffs"],
    queryFn: tariffsApi.list,
  });
}

export function useCreateTariff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TariffInput) => tariffsApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tariffs"] }),
  });
}

export function useUpdateTariff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<TariffInput> }) => tariffsApi.update(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tariffs"] }),
  });
}

export function useToggleTariff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tariffsApi.toggle(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tariffs"] }),
  });
}
