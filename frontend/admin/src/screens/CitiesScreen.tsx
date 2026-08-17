import { useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Modal } from "@/shared/components/Modal";
import { Num } from "@/shared/components/Num";
import { useCities, useDeleteCity, useSaveCity } from "@/shared/hooks/useCities";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { formatDate } from "@/shared/lib/format";
import type { StateCity } from "@/shared/api/types";

/** Which city each state is sold as.
 *
 * The pool's real geography comes from exit IPs, and those resolve to wherever a carrier's
 * address block happens to sit — Rolling Meadows, Sun Prairie, Saint Francis. Nobody shops
 * for those. The client organises their farm by state instead, writes it into each phone's
 * name (`att113_NV`), and decides here what that state is sold as.
 *
 * Two lists on purpose. The mapping is what an operator maintains; `unmapped` is what the
 * pool is asking them for — states already present in phone names with no city yet. Without
 * the second, a newly named batch keeps its exit-IP city and nobody knows a row is missing.
 */
export function CitiesScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useCities();
  const saveMutation = useSaveCity();
  const deleteMutation = useDeleteCity();

  const [editing, setEditing] = useState<{ state: string; city: string; isNew: boolean } | null>(
    null,
  );
  const [deleting, setDeleting] = useState<StateCity | null>(null);

  async function handleSave() {
    if (!editing) return;
    const state = editing.state.trim().toUpperCase();
    try {
      await saveMutation.mutateAsync({ state, city: editing.city.trim() });
      toast.success(`${state} → ${editing.city.trim()}`);
      setEditing(null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleDelete() {
    if (!deleting) return;
    try {
      await deleteMutation.mutateAsync(deleting.state_code);
      toast.success(strings.cities.deleted);
      setDeleting(null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead title={strings.cities.title} subtitle={strings.cities.subtitle} />

      {isLoading ? (
        <Skeleton className="h-[220px] rounded-lg" />
      ) : isError ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <>
          {/* States seen in phone names with nothing mapped — the work this screen is for.
              Above the table because it is the only part that needs acting on. */}
          {data && data.unmapped.length > 0 && (
            <div className="mb-5 rounded-lg border border-warning-line bg-warning-soft px-[18px] py-3.5">
              <div className="text-[.88rem] font-semibold text-warning">
                {strings.cities.unmappedTitle}
              </div>
              <p className="mt-0.5 text-[.8rem] text-text-2">{strings.cities.unmappedHint}</p>
              <div className="mt-2.5 flex flex-wrap gap-2">
                {data.unmapped.map((u) => (
                  <button
                    key={u.state_code}
                    type="button"
                    onClick={() => setEditing({ state: u.state_code, city: "", isNew: true })}
                    className="rounded-full border border-warning-line bg-surface px-3 py-1 font-mono text-[.78rem] text-text hover:border-accent hover:text-accent"
                  >
                    {u.state_code} · <Num value={u.connections} />
                  </button>
                ))}
              </div>
            </div>
          )}

          <Panel>
            <Panel.Head
              title={strings.cities.mappingTitle}
              subtitle={strings.cities.mappingHint}
              actions={
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setEditing({ state: "", city: "", isNew: true })}
                >
                  {strings.cities.add}
                </Button>
              }
            />
            {data && data.items.length === 0 ? (
              <EmptyState title={strings.cities.empty} hint={strings.cities.emptyHint} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[.85rem]">
                  <thead>
                    <tr className="border-b border-border text-left">
                      {[
                        strings.cities.colState,
                        strings.cities.colCity,
                        strings.cities.colConnections,
                        strings.cities.colUpdated,
                        "",
                      ].map((h) => (
                        <th
                          key={h}
                          className="px-[14px] py-2.5 text-[.7rem] font-semibold uppercase tracking-[.06em] text-text-3"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data?.items.map((row) => (
                      <tr key={row.state_code} className="border-b border-border last:border-b-0">
                        <td className="px-[14px] py-3 font-mono text-text">{row.state_code}</td>
                        <td className="px-[14px] py-3 text-text">{row.city}</td>
                        {/* How many phones this row currently speaks for. A row covering
                            zero phones is not wrong — the client may be preparing for a
                            batch that has not arrived yet. */}
                        <td className="px-[14px] py-3">
                          <Num value={row.connections} className="text-text-2" />
                        </td>
                        <td className="px-[14px] py-3 font-mono text-[.8rem] text-text-3">
                          {formatDate(row.updated_at)}
                        </td>
                        <td className="px-[14px] py-3">
                          <div className="flex justify-end gap-1.5">
                            <Button
                              variant="quiet"
                              size="sm"
                              onClick={() =>
                                setEditing({ state: row.state_code, city: row.city, isNew: false })
                              }
                            >
                              {strings.common.edit}
                            </Button>
                            <Button variant="danger" size="sm" onClick={() => setDeleting(row)}>
                              {strings.common.delete}
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
        </>
      )}

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.isNew ? strings.cities.add : strings.cities.edit}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              {strings.common.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              isLoading={saveMutation.isPending}
              disabled={!editing?.state.trim() || !editing?.city.trim()}
            >
              {strings.common.save}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            label={strings.cities.colState}
            hint={strings.cities.stateHint}
            value={editing?.state ?? ""}
            maxLength={2}
            // Locked when editing: the state is the row's identity, so changing it here
            // would silently create a second row and leave the first behind.
            disabled={editing !== null && !editing.isNew}
            onChange={(e) =>
              setEditing((prev) => (prev ? { ...prev, state: e.target.value.toUpperCase() } : prev))
            }
          />
          <Input
            label={strings.cities.colCity}
            hint={strings.cities.cityHint}
            value={editing?.city ?? ""}
            onChange={(e) => setEditing((prev) => (prev ? { ...prev, city: e.target.value } : prev))}
          />
        </div>
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={handleDelete}
        title={strings.cities.deleteTitle}
        description={strings.cities.deleteBody}
        confirmLabel={strings.common.delete}
        danger
        isSubmitting={deleteMutation.isPending}
      />
    </div>
  );
}
