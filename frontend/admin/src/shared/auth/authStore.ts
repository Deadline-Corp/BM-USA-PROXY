import { create } from "zustand";
import type { Admin } from "@/shared/api/types";

// Access token lives in memory ONLY — never localStorage/sessionStorage.
// The refresh token is an httpOnly cookie the browser sends automatically;
// this store just tracks the short-lived access token + the current admin.
interface AuthState {
  accessToken: string | null;
  admin: Admin | null;
  /** Set once the very first /me or /auth/refresh attempt has resolved
   * (success or failure) so the router knows whether to show a splash
   * or redirect to /login. */
  isBootstrapped: boolean;
  setSession: (accessToken: string, admin: Admin) => void;
  setAccessToken: (accessToken: string) => void;
  setBootstrapped: () => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  admin: null,
  isBootstrapped: false,
  setSession: (accessToken, admin) => set({ accessToken, admin }),
  setAccessToken: (accessToken) => set({ accessToken }),
  setBootstrapped: () => set({ isBootstrapped: true }),
  clearSession: () => set({ accessToken: null, admin: null }),
}));

// `isOwner` and the <RequireRole> wrapper that used it are gone with the role tiers.
// Being signed in is the whole authorisation model: every admin can do everything, and
// the audit log is what records who did it.
