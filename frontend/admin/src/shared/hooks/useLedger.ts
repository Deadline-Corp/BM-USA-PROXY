import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { paymentsApi } from "@/shared/api/endpoints";
import type { ListParams } from "@/shared/api/types";

/** Resolve a deposit the watcher parked. Refreshes the ledger so the row moves on. */
export function useResolveDeposit() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["ledger"] });
  return {
    attach: useMutation({
      mutationFn: (v: { depositId: number; orderPublicId: string; note?: string }) =>
        paymentsApi.attachDeposit(v.depositId, {
          order_public_id: v.orderPublicId,
          note: v.note,
        }),
      onSuccess: invalidate,
    }),
    writeOff: useMutation({
      mutationFn: (v: { depositId: number; reason: string }) =>
        paymentsApi.writeOffDeposit(v.depositId, { reason: v.reason }),
      onSuccess: invalidate,
    }),
  };
}

export function useDepositLedger(params: ListParams) {
  return useQuery({
    queryKey: ["ledger", params],
    queryFn: () => paymentsApi.ledger(params),
  });
}

export function useLedgerSummary() {
  return useQuery({
    queryKey: ["ledger", "summary"],
    queryFn: paymentsApi.ledgerSummary,
  });
}
