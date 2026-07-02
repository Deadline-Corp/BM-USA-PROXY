import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { initDataRaw, restoreInitData } from "@telegram-apps/sdk-react";
import { setAuthInitData, setDevBypassTgId } from "../api/client";

type AuthState =
  | { status: "loading" }
  | { status: "authenticated" }
  | { status: "dev-bypass" }
  | { status: "no-telegram-context" };

const AuthContext = createContext<AuthState>({ status: "loading" });

export function useAuthState(): AuthState {
  return useContext(AuthContext);
}

const DEV_TG_ID = "700001";

/**
 * Resolves Telegram initData once at bootstrap and wires it into the fetch
 * client. Falls back to the ?dev=1 dev-bypass header in dev builds. See the
 * README for why the dev bypass currently 403s against a real backend.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const devRequested = useMemo(() => {
    if (!import.meta.env.DEV) return false;
    const params = new URLSearchParams(window.location.search);
    return params.get("dev") === "1";
  }, []);

  useEffect(() => {
    if (devRequested) {
      setDevBypassTgId(DEV_TG_ID);
      setState({ status: "dev-bypass" });
      return;
    }

    try {
      // restore() populates the initData signals from window.Telegram.WebApp
      // (or the launch-params URL fragment) — it must run before reading
      // initDataRaw(), which is a Signal<string | undefined> rather than a
      // plain function call.
      restoreInitData();
      const raw = initDataRaw();
      if (raw) {
        setAuthInitData(raw);
        setState({ status: "authenticated" });
      } else {
        setState({ status: "no-telegram-context" });
      }
    } catch {
      setState({ status: "no-telegram-context" });
    }
  }, [devRequested]);

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}
