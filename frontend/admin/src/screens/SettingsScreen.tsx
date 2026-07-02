import { PageHead } from "@/shared/components/PageHead";
import { strings } from "@/shared/strings";
import { RequireRole } from "@/shared/auth/RequireRole";
import { AppSettingsPanel } from "@/screens/settings/AppSettingsPanel";
import { TermsPanel } from "@/screens/settings/TermsPanel";
import { AdminsPanel } from "@/screens/settings/AdminsPanel";
import { AuditPanel } from "@/screens/settings/AuditPanel";

export function SettingsScreen() {
  return (
    <div>
      <PageHead title={strings.settings.title} subtitle={strings.settings.subtitle} />

      <div className="flex flex-col gap-4">
        <AppSettingsPanel />
        <TermsPanel />
        <RequireRole role="owner">
          <AdminsPanel />
        </RequireRole>
        <AuditPanel />
      </div>
    </div>
  );
}
