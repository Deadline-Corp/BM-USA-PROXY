import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { citiesApi } from "@/shared/api/endpoints";

export function useCities() {
  return useQuery({
    queryKey: ["cities"],
    queryFn: citiesApi.list,
  });
}

export function useSaveCity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ state, city }: { state: string; city: string }) =>
      citiesApi.save(state, city),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cities"] });
      // The pool screen and the issue-access pickers both read cities that this decides.
      qc.invalidateQueries({ queryKey: ["pool"] });
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

export function useDeleteCity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (state: string) => citiesApi.remove(state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cities"] });
      qc.invalidateQueries({ queryKey: ["pool"] });
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}
