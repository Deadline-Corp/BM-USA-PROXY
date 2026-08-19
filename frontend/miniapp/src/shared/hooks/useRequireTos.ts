import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMe } from "./useMe";
import { rememberReturnTo } from "../auth/termsRedirect";

/**
 * Guards an action (buy / trial) behind `/me`.tos_accepted. If ToS have not
 * been accepted, redirects to /terms and remembers the current location so
 * the user returns here after accepting, and returns false so the caller
 * skips the action. Returns true when the action may proceed.
 */
export function useRequireTos() {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const location = useLocation();

  // `returnTo` is for callers that can describe what the person was DOING rather
  // than merely where they were standing. Coming back to a bare `/catalog` is how
  // a first purchase used to end: you press Buy, fill in your email, accept — and
  // land on the plan list again with nothing to show that you got anywhere. The
  // catalogue passes `/catalog?buy=<plan>` and resumes into the buy sheet.
  return useCallback(
    (returnTo?: string) => {
      if (me?.tos_accepted === false) {
        rememberReturnTo(returnTo ?? `${location.pathname}${location.search}`);
        navigate("/terms");
        return false;
      }
      return true;
    },
    [me, navigate, location],
  );
}
