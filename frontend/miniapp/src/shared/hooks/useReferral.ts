import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Referral, ReferralPayoutBody, ReferralPayoutResponse } from "../api/types";

export const referralQueryKey = ["referral"] as const;

export function useReferral() {
  return useQuery({
    queryKey: referralQueryKey,
    queryFn: ({ signal }) => api.get<Referral>("/referral", signal),
  });
}

/**
 * ASSUMPTION: the API contract in the task spec does not name a payout-
 * request endpoint. POST /referral/payout is not present in the backend
 * router read for this build (app/api/twa/router.py only exposes GET
 * /referral). This mutation is wired for forward-compatibility and will
 * 404 against today's backend — the form still validates and submits
 * client-side so the screen isn't dead weight once the endpoint exists.
 */
export function useRequestPayout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReferralPayoutBody) =>
      api.post<ReferralPayoutResponse>("/referral/payout", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: referralQueryKey });
    },
  });
}
