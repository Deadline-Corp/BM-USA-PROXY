import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { referralsApi } from "@/shared/api/endpoints";
import type { ListParams, ReferralSettings } from "@/shared/api/types";

export function useReferralSummary() {
  return useQuery({ queryKey: ["referrals", "summary"], queryFn: referralsApi.summary });
}

export function useReferralLedger(params: ListParams) {
  return useQuery({ queryKey: ["referrals", "ledger", params], queryFn: () => referralsApi.ledger(params) });
}

export function usePayouts(status?: string) {
  return useQuery({ queryKey: ["payouts", status], queryFn: () => referralsApi.payouts(status) });
}

export function useApprovePayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => referralsApi.approvePayout(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payouts"] });
      qc.invalidateQueries({ queryKey: ["referrals"] });
    },
  });
}

export function useRejectPayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => referralsApi.rejectPayout(id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payouts"] });
      qc.invalidateQueries({ queryKey: ["referrals"] });
    },
  });
}

export function useMarkPayoutPaid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, tx_hash }: { id: string; tx_hash: string }) => referralsApi.markPayoutPaid(id, tx_hash),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payouts"] });
      qc.invalidateQueries({ queryKey: ["referrals"] });
    },
  });
}

export function useReferralSettings() {
  return useQuery({ queryKey: ["referrals", "settings"], queryFn: referralsApi.getSettings });
}

export function useUpdateReferralSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<ReferralSettings>) => referralsApi.updateSettings(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["referrals", "settings"] }),
  });
}
