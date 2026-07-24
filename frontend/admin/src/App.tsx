import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/layout/AppShell";
import { AuthGate } from "@/shared/auth/AuthGate";
import { LoginScreen } from "@/screens/LoginScreen";
import { DashboardScreen } from "@/screens/DashboardScreen";
import { ClientsScreen } from "@/screens/ClientsScreen";
import { RequestsScreen } from "@/screens/RequestsScreen";
import { PoolsScreen } from "@/screens/PoolsScreen";
import { PackagesScreen } from "@/screens/PackagesScreen";
import { TariffsScreen } from "@/screens/TariffsScreen";
import { OrdersScreen } from "@/screens/OrdersScreen";
import { ReferralsScreen } from "@/screens/ReferralsScreen";
import { LedgerScreen } from "@/screens/LedgerScreen";
import { BroadcastsScreen } from "@/screens/BroadcastsScreen";
import { PublicationsScreen } from "@/screens/PublicationsScreen";
import { FaqScreen } from "@/screens/FaqScreen";
import { NotificationsScreen } from "@/screens/NotificationsScreen";
import { SettingsScreen } from "@/screens/SettingsScreen";
import { NotFoundScreen } from "@/screens/NotFoundScreen";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />

      <Route
        element={
          <AuthGate>
            <AppShell />
          </AuthGate>
        }
      >
        <Route path="/" element={<DashboardScreen />} />
        <Route path="/clients" element={<ClientsScreen />} />
        <Route path="/requests" element={<RequestsScreen />} />
        <Route path="/pools" element={<PoolsScreen />} />
        <Route path="/packages" element={<PackagesScreen />} />
        <Route path="/tariffs" element={<TariffsScreen />} />
        <Route path="/orders" element={<OrdersScreen />} />
        <Route path="/ledger" element={<LedgerScreen />} />
        <Route path="/referrals" element={<ReferralsScreen />} />
        <Route path="/broadcasts" element={<BroadcastsScreen />} />
        <Route path="/publications" element={<PublicationsScreen />} />
        <Route path="/faq" element={<FaqScreen />} />
        <Route path="/notifications" element={<NotificationsScreen />} />
        <Route path="/settings" element={<SettingsScreen />} />
      </Route>

      <Route path="*" element={<NotFoundScreen />} />
    </Routes>
  );
}
