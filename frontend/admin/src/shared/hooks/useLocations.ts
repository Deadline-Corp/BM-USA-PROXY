import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { locationsApi } from "@/shared/api/endpoints";
import type { LocationInput } from "@/shared/api/types";

export function useLocations() {
  return useQuery({
    queryKey: ["locations"],
    queryFn: locationsApi.list,
  });
}

// Renaming, deactivating, or reassigning a city changes what the connections list and pool
// summary show for every device on it (city/state text is resolved server-side from the
// Location row on every read) — so every mutation below invalidates those alongside
// "locations" itself, not just the locations table.
function invalidateLocationDependents(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["locations"] });
  qc.invalidateQueries({ queryKey: ["connections"] });
  qc.invalidateQueries({ queryKey: ["pool", "summary"] });
}

export function useCreateLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LocationInput) => locationsApi.create(body),
    onSuccess: () => invalidateLocationDependents(qc),
  });
}

export function useUpdateLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<LocationInput> }) =>
      locationsApi.update(id, body),
    onSuccess: () => invalidateLocationDependents(qc),
  });
}

export function useToggleLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => locationsApi.toggle(id),
    onSuccess: () => invalidateLocationDependents(qc),
  });
}

export function useDeleteLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => locationsApi.remove(id),
    onSuccess: () => invalidateLocationDependents(qc),
  });
}
