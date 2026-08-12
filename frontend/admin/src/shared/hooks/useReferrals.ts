import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { referralsApi } from "@/shared/api/endpoints";
import type { ListParams } from "@/shared/api/types";

export function useReferralSummary() {
  return useQuery({ queryKey: ["referrals", "summary"], queryFn: referralsApi.summary });
}

export function useReferralLedger(params: ListParams) {
  return useQuery({ queryKey: ["referrals", "ledger", params], queryFn: () => referralsApi.ledger(params) });
}

export function usePayouts(params?: ListParams) {
  return useQuery({
    queryKey: ["payouts", params],
    queryFn: () => referralsApi.payouts(params),
    // the watcher closes a payout on its own once it sees the transfer on-chain — poll so
    // the row flips to 'paid' without the operator reloading the page
    refetchInterval: 15_000,
  });
}

export function usePayoutInstruction(id: string | null) {
  return useQuery({
    queryKey: ["payouts", "instruction", id],
    queryFn: () => referralsApi.payoutInstruction(id as string),
    enabled: id !== null,
  });
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

// The referral-settings hooks lived here for the panel on the Referrals screen. Settings
// owns those three keys now, through the generic /settings bag. The dedicated
// GET/PATCH /settings/referral endpoints still exist — they are the operator-editable
// route, kept for the day we decide the commission dial should not be owner-only.
