import { useState } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Modal } from "@/shared/components/Modal";
import { Input } from "@/shared/components/form/Input";
import { Select } from "@/shared/components/form/Select";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import { IconPlus } from "@/shared/components/icons";
import { useAdmins, useCreateAdmin, useUpdateAdmin } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { AdminAccount, AdminRole } from "@/shared/api/types";

/** Only rendered inside <RequireRole role="owner"> by the parent screen —
 * see design-spec.md §9. Not gated internally here on purpose: if this
 * component is mounted at all, the viewer is already an owner. */
export function AdminsPanel() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useAdmins();
  const createMutation = useCreateAdmin();
  const updateMutation = useUpdateAdmin();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AdminAccount | null>(null);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<AdminRole>("operator");
  const [password, setPassword] = useState("");

  function openCreate() {
    setEditing(null);
    setEmail("");
    setDisplayName("");
    setRole("operator");
    setPassword("");
    setFormOpen(true);
  }

  function openEdit(a: AdminAccount) {
    setEditing(a);
    setEmail(a.email);
    setDisplayName(a.display_name);
    setRole(a.role);
    setPassword("");
    setFormOpen(true);
  }

  async function handleSave() {
    try {
      if (editing) {
        await updateMutation.mutateAsync({
          id: editing.id,
          body: { email, display_name: displayName, role, ...(password ? { password } : {}) },
        });
        toast.success("Admin updated");
      } else {
        await createMutation.mutateAsync({ email, display_name: displayName, role, password });
        toast.success("Admin created");
      }
      setFormOpen(false);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Panel>
      <Panel.Head
        title={strings.settings.admins}
        actions={
          <Button variant="primary" size="sm" onClick={openCreate}>
            <IconPlus />
            {strings.settings.addAdmin}
          </Button>
        }
      />
      <div className="flex flex-col">
        {isLoading ? (
          <Skeleton className="h-32 m-4" />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : (data?.length ?? 0) === 0 ? (
          <EmptyState title="No admins yet" />
        ) : (
          data?.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-[18px] py-3.5 border-b border-border last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="text-[.86rem] text-text font-medium">{a.display_name}</div>
                <div className="text-[.78rem] text-text-3 mt-0.5">{a.email}</div>
              </div>
              <StatusBadge tone={a.is_active ? "success" : "neutral"} label={a.is_active ? strings.common.active : strings.common.inactive} />
              <span className="text-[.78rem] text-text-2 capitalize w-20">{a.role}</span>
              <Button variant="quiet" size="sm" onClick={() => openEdit(a)}>
                {strings.common.edit}
              </Button>
            </div>
          ))
        )}
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? "Edit admin" : strings.settings.addAdmin}
        footer={
          <>
            <Button variant="ghost" onClick={() => setFormOpen(false)}>
              {strings.common.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              disabled={!email.trim() || !displayName.trim() || (!editing && !password.trim())}
              isLoading={createMutation.isPending || updateMutation.isPending}
            >
              {editing ? strings.common.save : strings.common.create}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input label={strings.auth.emailLabel} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as AdminRole)}>
            <option value="owner">Owner</option>
            <option value="operator">Operator</option>
          </Select>
          <Input
            label={editing ? "New password (leave blank to keep current)" : strings.auth.passwordLabel}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
      </Modal>
    </Panel>
  );
}
