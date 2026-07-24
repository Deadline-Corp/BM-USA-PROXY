import { useQuery } from "@tanstack/react-query";
import { paymentsApi } from "@/shared/api/endpoints";
import type { ListParams } from "@/shared/api/types";

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
