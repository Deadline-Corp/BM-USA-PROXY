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

  return useCallback(() => {
    if (me?.tos_accepted === false) {
      rememberReturnTo(`${location.pathname}${location.search}`);
      navigate("/terms");
      return false;
    }
    return true;
  }, [me, navigate, location]);
}
