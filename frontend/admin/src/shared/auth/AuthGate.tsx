import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/shared/auth/authStore";

/** Route guard: unauthenticated visitors are redirected to /login,
 * preserving the originally requested path so login can send them back. */
export function AuthGate({ children }: { children: ReactNode }) {
  const admin = useAuthStore((s) => s.admin);
  const location = useLocation();

  if (!admin) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
