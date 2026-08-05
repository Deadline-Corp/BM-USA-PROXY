import { useState } from "react";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { useResolveDeposit } from "@/shared/hooks/useLedger";
import { formatChain, formatCryptoAmount, formatNetwork } from "@/shared/lib/format";
import { strings } from "@/shared/strings";
import type { DepositLedgerEntry } from "@/shared/api/types";

/**
 * What an operator does with money the watcher would not guess about.
 *
 * Two outcomes, deliberately both explicit: credit it to an order (the buyer paid, we just
 * could not tie it automatically), or close it without crediting anyone (refunded
 * elsewhere, dust, someone else's transfer). There is no "delete" — the ledger is
 * append-only, so either choice adds a row on top of the original observation.
 */
export function ResolveDepositModal({
  deposit,
  onClose,
}: {
  deposit: DepositLedgerEntry | null;
  onClose: () => void;
}) {
  const { attach, writeOff } = useResolveDeposit();
  const [orderId, setOrderId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!deposit) return null;
  const busy = attach.isPending || writeOff.isPending;

  function fail(e: unknown) {
    const msg =
      typeof e === "object" && e && "response" in e
        ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? null)
        : null;
    setError(msg ?? strings.common.errorHint);
  }

  function close() {
    setOrderId("");
    setReason("");
    setError(null);
    onClose();
  }

  return (
    <Modal open onClose={close} title={strings.ledger.resolveTitle}>
      <div className="mb-4 rounded border border-border bg-surface-2 p-3 text-[.82rem]">
        <div className="flex justify-between gap-3">
          <span className="text-text-3">{formatChain(deposit.chain)}</span>
          <span className="font-mono text-text">
            {formatCryptoAmount(deposit.amount)} {deposit.asset} {formatNetwork(deposit.network)}
          </span>
        </div>
        <div className="mt-1 truncate font-mono text-[.72rem] text-text-3">{deposit.txid}</div>
      </div>

      {error ? (
        <div className="mb-3 rounded border border-danger/40 bg-danger/5 px-3 py-2 text-[.8rem] text-danger">
          {error}
        </div>
      ) : null}

      {/* ── credit it to an order ── */}
      <label className="mb-1 block text-[.75rem] font-semibold uppercase tracking-wide text-text-3">
        {strings.ledger.attachLabel}
      </label>
      <input
        className="mb-2 w-full rounded border border-border bg-surface px-3 py-2 font-mono text-[.8rem] text-text"
        placeholder={strings.ledger.attachPlaceholder}
        value={orderId}
        onChange={(e) => setOrderId(e.target.value)}
      />
      <Button
        variant="primary"
        className="w-full"
        disabled={busy || orderId.trim().length < 8}
        onClick={async () => {
          setError(null);
          try {
            await attach.mutateAsync({ depositId: Number(deposit.id), orderPublicId: orderId.trim() });
            close();
          } catch (e) {
            fail(e);
          }
        }}
      >
        {strings.ledger.attachAction}
      </Button>

      <div className="my-4 border-t border-border" />

      {/* ── close it without crediting anyone ── */}
      <label className="mb-1 block text-[.75rem] font-semibold uppercase tracking-wide text-text-3">
        {strings.ledger.writeOffLabel}
      </label>
      <input
        className="mb-2 w-full rounded border border-border bg-surface px-3 py-2 text-[.8rem] text-text"
        placeholder={strings.ledger.writeOffPlaceholder}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <Button
        variant="ghost"
        className="w-full"
        disabled={busy || reason.trim().length < 3}
        onClick={async () => {
          setError(null);
          try {
            await writeOff.mutateAsync({ depositId: Number(deposit.id), reason: reason.trim() });
            close();
          } catch (e) {
            fail(e);
          }
        }}
      >
        {strings.ledger.writeOffAction}
      </Button>
    </Modal>
  );
}
