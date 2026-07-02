import { useEffect } from "react";
import type { ReactNode } from "react";
import { useAuthStore } from "@/shared/auth/authStore";
import { authApi } from "@/shared/api/endpoints";

/** On mount, tries to silently resume a session from the httpOnly refresh
 * cookie: POST /auth/refresh → GET /me. If either fails (no cookie, or
 * cookie expired), the store just stays cleared and AuthGate below sends
 * the user to /login. Runs once per full page load. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const setSession = useAuthStore((s) => s.setSession);
  const setBootstrapped = useAuthStore((s) => s.setBootstrapped);
  const isBootstrapped = useAuthStore((s) => s.isBootstrapped);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const { access_token } = await authApi.refresh();
        if (cancelled) return;
        useAuthStore.getState().setAccessToken(access_token);
        const admin = await authApi.me();
        if (cancelled) return;
        setSession(access_token, admin);
      } catch {
        // No valid refresh cookie — stay logged out, that's expected on a
        // fresh browser / after logout / after refresh-token expiry.
      } finally {
        if (!cancelled) setBootstrapped();
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!isBootstrapped) {
    return (
      <div className="min-h-screen grid place-items-center bg-bg">
        <div className="w-8 h-8 rounded-full border-2 border-border-2 border-t-accent animate-spin" />
      </div>
    );
  }

  return <>{children}</>;
}
