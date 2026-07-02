import type { ReactNode } from "react";
import { useAuthStore, isOwner } from "@/shared/auth/authStore";

interface RequireRoleProps {
  /** Currently only "owner" is gated per the task spec (Settings→admins,
   * Terms publish, mark-paid, referral settings). Extend if more roles
   * need gating later. */
  role: "owner";
  children: ReactNode;
  /** Optional fallback rendered instead of nothing — used sparingly, e.g.
   * a "owner only" chip where a whole section can't just vanish. */
  fallback?: ReactNode;
}

/** Conditionally renders owner-only UI. Per design-spec.md §9 this is a
 * real conditional render (DOM node removed), not a disabled input with a
 * tooltip — a Support-role operator should not learn the feature exists. */
export function RequireRole({ role, children, fallback = null }: RequireRoleProps) {
  const admin = useAuthStore((s) => s.admin);
  const allowed = role === "owner" ? isOwner(admin) : false;
  return allowed ? <>{children}</> : <>{fallback}</>;
}
