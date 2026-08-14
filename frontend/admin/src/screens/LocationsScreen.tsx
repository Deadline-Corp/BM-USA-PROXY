import { useMemo, useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Switch } from "@/shared/components/Switch";
import { Num } from "@/shared/components/Num";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { TableSkeleton } from "@/shared/components/Skeleton";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { IconPlus, IconTrash } from "@/shared/components/icons";
import { useDeleteLocation, useLocations, useToggleLocation } from "@/shared/hooks/useLocations";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { formatCityState } from "@/shared/lib/format";
import type { Location } from "@/shared/api/types";
import { LocationFormModal } from "@/screens/locations/LocationFormModal";

export function LocationsScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useLocations();
  const toggleMutation = useToggleLocation();
  const deleteMutation = useDeleteLocation();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Location | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Location | null>(null);

  const rows = useMemo(() => data ?? [], [data]);

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }
  function openEdit(loc: Location) {
    setEditing(loc);
    setFormOpen(true);
  }

  async function handleToggle(id: string) {
    try {
      await toggleMutation.mutateAsync(id);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      toast.success("City deleted");
      setDeleteTarget(null);
    } catch (err) {
      // Most likely a Conflict: connections are still assigned to this city — the message
      // from the backend already says how many and suggests deactivating instead.
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead
        title={strings.locations.title}
        subtitle={strings.locations.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={openCreate}>
            <IconPlus />
            {strings.locations.create}
          </Button>
        }
      />

      <Panel>
        {isLoading ? (
          <TableSkeleton cols={6} />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No cities yet"
            action={
              <Button variant="ghost" size="sm" onClick={openCreate}>
                {strings.locations.create}
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[.86rem]">
              <thead>
                <tr>
                  {[
                    strings.locations.city,
                    strings.locations.stateCode,
                    strings.locations.connectionsCount,
                    strings.locations.sortOrder,
                    strings.locations.active,
                    "",
                  ].map((h) => (
                    <th
                      key={h}
                      className="text-left text-[.7rem] uppercase tracking-[.08em] text-text-3 font-semibold px-[14px] py-2.5 border-b border-border whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((loc) => (
                  <tr
                    key={loc.id}
                    className="border-b border-border last:border-b-0 hover:bg-surface-2 transition-colors duration-150 ease-brand"
                  >
                    <td className="px-[14px] py-3 text-text font-medium">{loc.city}</td>
                    <td className="px-[14px] py-3 font-mono text-[.82rem] text-text-2">{loc.state_code}</td>
                    <td className="px-[14px] py-3">
                      <Num value={loc.connections_count} className="text-text-2" />
                    </td>
                    <td className="px-[14px] py-3">
                      <Num value={loc.sort_order} className="text-text-2" />
                    </td>
                    <td className="px-[14px] py-3">
                      <Switch
                        checked={loc.is_active}
                        onChange={() => handleToggle(loc.id)}
                        disabled={toggleMutation.isPending}
                      />
                    </td>
                    <td className="px-[14px] py-3 text-right">
                      <div className="inline-flex items-center gap-1">
                        <Button variant="quiet" size="sm" onClick={() => openEdit(loc)}>
                          {strings.common.edit}
                        </Button>
                        <Button
                          variant="quiet"
                          size="sm"
                          onClick={() => setDeleteTarget(loc)}
                          aria-label={strings.common.delete}
                        >
                          <IconTrash />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <LocationFormModal open={formOpen} onClose={() => setFormOpen(false)} location={editing} />

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title={strings.locations.deleteTitle}
        description={
          deleteTarget
            ? `Delete "${formatCityState(deleteTarget.city, deleteTarget.state_code)}"? This cannot be undone.`
            : undefined
        }
        confirmLabel={strings.common.delete}
        danger
        isSubmitting={deleteMutation.isPending}
      />
    </div>
  );
}
