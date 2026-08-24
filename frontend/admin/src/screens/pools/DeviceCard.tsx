import { useState } from "react";
import clsx from "clsx";
import type { Connection, ConnectionUpdate } from "@/shared/api/types";
import { Switch } from "@/shared/components/Switch";
import { Num } from "@/shared/components/Num";
import { IconKebab } from "@/shared/components/icons";
import { OrderNumber } from "@/shared/components/OrderNumber";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { useRebootConnection, useUpdateConnection } from "@/shared/hooks/usePool";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";

interface DeviceCardProps {
  connection: Connection;
  onEdit: (c: Connection) => void;
}

export function DeviceCard({ connection: c, onEdit }: DeviceCardProps) {
  const toast = useToast();
  const updateMutation = useUpdateConnection();
  const rebootMutation = useRebootConnection();
  const [menuOpen, setMenuOpen] = useState(false);
  const [rebootConfirm, setRebootConfirm] = useState(false);

  const usagePct = c.slots_total > 0 ? Math.min(100, Math.round((c.slots_used / c.slots_total) * 100)) : 0;
  const isFull = c.online && c.slots_used >= c.slots_total;
  const status: "online" | "offline" | "full" = !c.online ? "offline" : isFull ? "full" : "online";

  const statusStyle = {
    online: "bg-success-soft text-success",
    offline: "bg-[rgba(147,167,181,.16)] text-text-3",
    full: "bg-warning-soft text-warning",
  }[status];

  const barColor = { online: "bg-accent", offline: "bg-text-3 opacity-50", full: "bg-warning" }[status];

  async function handleToggleSellable(next: boolean) {
    try {
      await updateMutation.mutateAsync({ id: c.id, body: { is_sellable: next } as ConnectionUpdate });
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleReboot() {
    try {
      await rebootMutation.mutateAsync(c.id);
      setRebootConfirm(false);
      toast.success(strings.pools.rebootSent);
    } catch (err) {
      // Leaves the dialog open. The common failure is the shared cooldown — the same
      // phone was rebooted from the mini app minutes ago — and that message belongs
      // next to the button that caused it, not on a screen the operator already left.
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <div
      className={clsx(
        "bg-surface border rounded-lg p-4 flex flex-col gap-2.5 transition-colors duration-150 ease-brand relative hover:border-border-2",
        status === "offline" && "opacity-60",
        status === "full" ? "border-warning-line" : "border-border",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-[.72rem] text-text-3 tracking-[.04em] mb-0.5">{c.external_id}</div>
          <div className="font-head text-[.97rem] font-semibold tracking-[-0.02em] text-text leading-tight">{c.city}</div>
          <div className="text-[.75rem] text-text-2 mt-px">{c.state}</div>
        </div>
        <span className={clsx("flex items-center gap-1.5 text-[.7rem] px-[9px] py-[3px] rounded-full flex-none leading-none", statusStyle)}>
          <span className="w-[5px] h-[5px] rounded-full bg-current flex-none" />
          {/* Busy, not Full. This chip answers "what is this phone doing" — Online, Busy,
              Offline is one vocabulary about a device. "Full" was capacity language about
              slots, and it sat next to a SLOTS 1/1 row that already says the same thing in
              numbers. The pool legend keeps Used because it counts slots, not phones. */}
          {status === "online" ? "Online" : status === "full" ? "Busy" : "Offline"}
        </span>
      </div>

      {/* A phone can be occupied without a single row of ours saying so — somebody made a
          proxy-access for it in the iproxy console. Saying it on the card is the whole
          point: without it this device reads as free here while it serves traffic there. */}
      {c.external_holds > 0 ? (
        <div
          className="flex items-center gap-1.5 rounded border border-warning-line bg-warning-soft px-2 py-1 text-[.72rem] text-warning"
          title={strings.pools.busyByAdminHint}
        >
          <span className="w-[5px] h-[5px] rounded-full bg-current flex-none" />
          {strings.pools.busyByAdmin}
        </div>
      ) : null}

      {/* Same reasoning as the row above: the allocator will not hand this phone out, and
          nothing else on the card says why. Slots read 0/1 and the chip says Online, so
          without this it looks like the pool is broken rather than spoken for. */}
      {c.reserved_for_order !== null ? (
        <div
          className="flex items-center gap-1.5 rounded border border-border-2 bg-surface-2 px-2 py-1 text-[.72rem] text-text-2"
          title={strings.pools.reservedHint}
        >
          <span className="w-[5px] h-[5px] rounded-full bg-current flex-none" />
          {strings.pools.reserved}
          <OrderNumber value={c.reserved_for_order} />
        </div>
      ) : null}

      <div className="flex items-center gap-1.5 text-[.76rem] text-text-2">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="w-[13px] h-[13px] text-text-3 flex-none">
          <path d="M4 20h16" />
          <path d="M6 20v-4" />
          <path d="M10 20v-8" />
          <path d="M14 20v-12" />
          <path d="M18 20V4" />
        </svg>
        {c.carrier}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between items-baseline">
          <span className="text-[.68rem] uppercase tracking-[.07em] text-text-3">{strings.pools.slots}</span>
          <span className="font-mono tabular-nums text-[.82rem] text-text-2">
            <Num value={c.slots_used} />/<Num value={c.slots_total} />
          </span>
        </div>
        <div className="h-1 bg-surface-2 rounded-full overflow-hidden">
          <div className={clsx("h-full rounded-full transition-[width] duration-300 ease-brand", barColor)} style={{ width: `${usagePct}%` }} />
        </div>
      </div>

      {/* No "last rotated" here. It only ever recorded rotations WE triggered, so it said
          nothing about when the phone's address actually changed — a device whose IP moved
          an hour ago on iproxy's own schedule still showed a timestamp from days back.
          A number that looks like an answer to a question it does not answer is worse than
          no number: iproxy's ip_updated_at is the real one, if this is ever wanted back. */}
      <div className="flex items-center justify-end pt-[9px] border-t border-border">
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 cursor-pointer" title={strings.pools.sellable}>
            <span className="text-[.7rem] text-text-3">{strings.pools.sellable}</span>
            <Switch checked={c.is_sellable} onChange={(e) => handleToggleSellable(e.target.checked)} disabled={updateMutation.isPending} />
          </label>
          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              onBlur={() => window.setTimeout(() => setMenuOpen(false), 120)}
              className="w-[30px] h-[30px] rounded-lg border border-transparent text-text-3 hover:bg-surface-2 hover:border-border hover:text-text-2 transition-colors duration-150 ease-brand grid place-items-center"
              aria-label="More actions"
            >
              <IconKebab className="w-4 h-4" />
            </button>
            {menuOpen && (
              <div className="absolute top-[calc(100%+4px)] right-0 z-20 bg-surface border border-border-2 rounded-lg shadow-menu min-w-[150px] overflow-hidden">
                <button
                  type="button"
                  onMouseDown={() => onEdit(c)}
                  className="flex items-center gap-2 w-full text-left px-[13px] py-2.5 text-[.8rem] text-text-2 hover:bg-surface-2 hover:text-text transition-colors duration-100"
                >
                  {strings.pools.editConnection}
                </button>
                <button
                  type="button"
                  onMouseDown={() => setRebootConfirm(true)}
                  className="flex items-center gap-2 w-full text-left px-[13px] py-2.5 text-[.8rem] text-text-2 hover:bg-surface-2 hover:text-text transition-colors duration-100 border-t border-border"
                >
                  {strings.pools.rebootDevice}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={rebootConfirm}
        onClose={() => setRebootConfirm(false)}
        onConfirm={handleReboot}
        title={strings.pools.rebootConfirmTitle}
        description={
          (c.slots_used > 0
            ? `${strings.pools.rebootConfirmBusy} ${strings.pools.rebootConfirmBody}`
            : strings.pools.rebootConfirmBody) +
          `

${strings.pools.rebootOwnerModeNote}`
        }
        confirmLabel={strings.pools.rebootCta}
        // Danger only when somebody is actually on it. A reboot of an idle phone costs
        // nothing, and painting every one of them red teaches the operator to ignore red.
        danger={c.slots_used > 0}
        isSubmitting={rebootMutation.isPending}
      />
    </div>
  );
}
