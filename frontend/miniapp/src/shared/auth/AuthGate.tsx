import type { ReactNode } from "react";
import { useAuthState } from "./AuthProvider";
import { useBanned } from "./bannedState";
import { OpenInTelegram } from "../components/OpenInTelegram";
import { BannedScreen } from "../components/BannedScreen";

/**
 * Blocks the whole route tree until Telegram initData (or the ?dev=1
 * bypass) has resolved. Renders OpenInTelegram if there's no Telegram
 * context and no dev bypass — the app is otherwise unusable without an
 * identity to attach to every /api/twa request.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuthState();
  const banned = useBanned();

  // Once any request has reported the account banned, block the whole app —
  // regardless of auth phase — with a dedicated, actionable screen.
  if (banned) {
    return <BannedScreen />;
  }

  if (auth.status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-app">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-2 border-t-accent" />
      </div>
    );
  }

  if (auth.status === "no-telegram-context") {
    return <OpenInTelegram />;
  }

  return <>{children}</>;
}
