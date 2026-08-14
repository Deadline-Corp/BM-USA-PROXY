import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AppLinks } from "../api/types";

// Same values as the backend fallback (app/services/settings.py::DEFAULT_CHANNEL_URL /
// DEFAULT_SUPPORT_URL). Used only while the request hasn't resolved yet or the endpoint is
// unreachable, so a link never renders empty.
export const DEFAULT_CHANNEL_URL = "https://t.me/usproxyclub";
export const DEFAULT_SUPPORT_URL = "https://t.me/usproxy_support";

/**
 * Channel/Support links, operator-editable in the admin Settings screen. Backed by a
 * public endpoint (no auth) on purpose — a banned account still needs the Support link to
 * dispute the ban, and BannedScreen shows it exactly where CurrentUser would 403.
 *
 * A moderate staleTime rather than Infinity (see usePaymentMethods): these links change
 * rarely, but when an operator does change one they go straight to the mini app to check
 * it landed, and that check must not require a reinstall to see the new value.
 */
export function useAppLinks() {
  return useQuery({
    queryKey: ["links"],
    queryFn: ({ signal }) => api.get<AppLinks>("/links", signal),
    staleTime: 5 * 60_000,
  });
}
