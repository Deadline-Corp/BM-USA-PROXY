import { useMemo, useState } from "react";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Switch } from "@/shared/components/Switch";
import { Num } from "@/shared/components/Num";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { TableSkeleton } from "@/shared/components/Skeleton";
import { IconPlus } from "@/shared/components/icons";
import { useTariffs, useToggleTariff } from "@/shared/hooks/useTariffs";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Tariff } from "@/shared/api/types";
import { TariffFormModal } from "@/screens/tariffs/TariffFormModal";

export function TariffsScreen() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useTariffs();
  const toggleMutation = useToggleTariff();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Tariff | null>(null);

  const rows = useMemo(() => data ?? [], [data]);

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }
  function openEdit(t: Tariff) {
    setEditing(t);
    setFormOpen(true);
  }

  async function handleToggle(id: string) {
    try {
      await toggleMutation.mutateAsync(id);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHead
        title={strings.tariffs.title}
        subtitle={strings.tariffs.subtitle}
        actions={
          <Button variant="primary" size="sm" onClick={openCreate}>
            <IconPlus />
            {strings.tariffs.create}
          </Button>
        }
      />

      <Panel>
        {isLoading ? (
          <TableSkeleton cols={6} />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : rows.length === 0 ? (
          <EmptyState title="No tariffs yet" action={<Button variant="ghost" size="sm" onClick={openCreate}>{strings.tariffs.create}</Button>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[.86rem]">
              <thead>
                <tr>
                  {[strings.tariffs.code, strings.tariffs.name, strings.tariffs.priceUsd, strings.tariffs.durationMinutes, strings.tariffs.maxUserSwaps, strings.tariffs.active, ""].map((h) => (
                    <th key={h} className="text-left text-[.7rem] uppercase tracking-[.08em] text-text-3 font-semibold px-[14px] py-2.5 border-b border-border whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id} className="border-b border-border last:border-b-0 hover:bg-surface-2 transition-colors duration-150 ease-brand">
                    <td className="px-[14px] py-3 font-mono text-[.82rem] text-text">{t.code}</td>
                    <td className="px-[14px] py-3 text-text font-medium">{t.name}</td>
                    <td className="px-[14px] py-3"><Num value={t.price_usd} usd className="text-text" /></td>
                    <td className="px-[14px] py-3"><Num value={t.duration_minutes} className="text-text-2" /></td>
                    <td className="px-[14px] py-3"><Num value={t.max_user_swaps} className="text-text-2" /></td>
                    <td className="px-[14px] py-3">
                      <Switch checked={t.is_active} onChange={() => handleToggle(t.id)} disabled={toggleMutation.isPending} />
                    </td>
                    <td className="px-[14px] py-3 text-right">
                      <Button variant="quiet" size="sm" onClick={() => openEdit(t)}>
                        {strings.common.edit}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <TariffFormModal open={formOpen} onClose={() => setFormOpen(false)} tariff={editing} />
    </div>
  );
}
