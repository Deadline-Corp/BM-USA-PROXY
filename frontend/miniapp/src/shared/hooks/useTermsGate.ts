import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { rememberReturnTo } from "../auth/termsRedirect";

/**
 * Wraps any order-creation call: if it throws an ApiError with status 428
 * (ToS not accepted), redirects to /terms and remembers the current
 * location so the user returns here after accepting. Any other error
 * rethrows unchanged for the caller's own error handling.
 */
export function useTermsGate() {
  const navigate = useNavigate();
  const location = useLocation();

  return useCallback(
    async <T,>(action: () => Promise<T>): Promise<T> => {
      try {
        return await action();
      } catch (error) {
        if (error instanceof ApiError && error.status === 428) {
          rememberReturnTo(`${location.pathname}${location.search}`);
          navigate("/terms");
        }
        throw error;
      }
    },
    [navigate, location],
  );
}
