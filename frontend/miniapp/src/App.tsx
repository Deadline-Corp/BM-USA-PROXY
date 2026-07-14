import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiError } from "./shared/api/client";
import { AuthProvider } from "./shared/auth/AuthProvider";
import { AuthGate } from "./shared/auth/AuthGate";
import { ToastProvider } from "./shared/components/Toast";
import { BottomNav } from "./shared/components/BottomNav";
import { HomeScreen } from "./screens/HomeScreen";
import { CatalogScreen } from "./screens/CatalogScreen";
import { CheckoutScreen } from "./screens/CheckoutScreen";
import { AccessScreen } from "./screens/AccessScreen";
import { AccessDetailScreen } from "./screens/AccessDetailScreen";
import { ReferralScreen } from "./screens/ReferralScreen";
import { FaqScreen } from "./screens/FaqScreen";
import { TermsScreen } from "./screens/TermsScreen";

function shouldRetry(failureCount: number, error: unknown): boolean {
  // Never retry client errors (4xx) — retry only on network failures/5xx,
  // and cap it low so a broken endpoint doesn't spin the UI forever.
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < 2;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetry,
      staleTime: 15_000,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});

/**
 * Persistent scroll area + bottom tab bar, matching the demo's .screens-m /
 * .tabbar split. Terms and Checkout render outside this shell (full-screen,
 * their own header/footer, no tab bar) — see the routes below.
 */
function TabbedShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-[var(--tg-vh)] flex-col bg-app">
      <main className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="mx-auto w-full max-w-[480px] px-4 pb-6 pt-4">{children}</div>
      </main>
      <BottomNav />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter basename="/app">
            <AuthGate>
              <Routes>
                {/* Full-screen — no tab bar. */}
                <Route path="/terms" element={<TermsScreen />} />
                <Route
                  path="/checkout/:orderId"
                  element={
                    <TabbedShell>
                      <CheckoutScreen />
                    </TabbedShell>
                  }
                />

                {/* Tabbed app shell. ToS acceptance is enforced per-action
                    (useRequireTos / useTermsGate in Home + Catalog + Access
                    Detail) rather than as a blanket route guard, so a user
                    can still browse Home/Catalog/FAQ read-only before
                    accepting — only mutating actions (buy, trial, extend)
                    redirect to /terms. */}
                <Route
                  path="/"
                  element={
                    <TabbedShell>
                      <HomeScreen />
                    </TabbedShell>
                  }
                />
                <Route
                  path="/catalog"
                  element={
                    <TabbedShell>
                      <CatalogScreen />
                    </TabbedShell>
                  }
                />
                <Route
                  path="/access"
                  element={
                    <TabbedShell>
                      <AccessScreen />
                    </TabbedShell>
                  }
                />
                <Route
                  path="/access/:publicId"
                  element={
                    <TabbedShell>
                      <AccessDetailScreen />
                    </TabbedShell>
                  }
                />
                <Route
                  path="/referral"
                  element={
                    <TabbedShell>
                      <ReferralScreen />
                    </TabbedShell>
                  }
                />
                <Route
                  path="/faq"
                  element={
                    <TabbedShell>
                      <FaqScreen />
                    </TabbedShell>
                  }
                />
              </Routes>
            </AuthGate>
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
