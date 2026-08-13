import { useState } from "react";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Modal } from "@/shared/components/Modal";
import { Input } from "@/shared/components/form/Input";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import { IconPlus } from "@/shared/components/icons";
import { useAdmins, useCreateAdmin, useUpdateAdmin } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { AdminAccount } from "@/shared/api/types";

/** Console accounts. There is no role to pick any more — every admin can do
 * everything, so the only things worth setting are who they are, their password, and
 * whether the account is still active. */
export function AdminsPanel() {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useAdmins();
  const createMutation = useCreateAdmin();
  const updateMutation = useUpdateAdmin();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AdminAccount | null>(null);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [telegram, setTelegram] = useState("");

  function openCreate() {
    setEditing(null);
    setEmail("");
    setDisplayName("");
    setPassword("");
    setTelegram("");
    setFormOpen(true);
  }

  function openEdit(a: AdminAccount) {
    setEditing(a);
    setEmail(a.email);
    setDisplayName(a.display_name);
    setPassword("");
    setTelegram(a.telegram_username ? `@${a.telegram_username}` : "");
    setFormOpen(true);
  }

  async function handleSave() {
    try {
      if (editing) {
        await updateMutation.mutateAsync({
          id: editing.id,
          body: {
            email,
            display_name: displayName,
            telegram_username: telegram.trim() || null,
            ...(password ? { password } : {}),
          },
        });
        toast.success("Admin updated");
      } else {
        await createMutation.mutateAsync({
          email,
          display_name: displayName,
          password,
          telegram_username: telegram.trim() || null,
        });
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
                {a.telegram_username ? (
                  <div className="text-[.78rem] text-text-3 mt-0.5">
                    @{a.telegram_username}
                    {/* Says whether a code could reach them. A handle on its own cannot be
                     * written to — the bot needs that person to have opened it first. */}
                    <span className={a.telegram_linked ? "text-success ml-1.5" : "text-warning-text ml-1.5"}>
                      {a.telegram_linked ? "· linked" : "· waiting for /start"}
                    </span>
                  </div>
                ) : null}
              </div>
              <StatusBadge tone={a.is_active ? "success" : "neutral"} label={a.is_active ? strings.common.active : strings.common.inactive} />
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
          <Input
            label="Telegram"
            placeholder="@operator"
            // Where their sign-in code is sent. A handle alone is not an address: the bot
            // cannot write first, so it is bound to a real chat when that person opens the
            // bot. Replacing the handle un-binds the old one — a new handle is a new person.
            hint={
              editing && editing.telegram_username && !editing.telegram_linked
                ? "Not linked yet — ask them to open the bot and press Start."
                : "Sign-in codes go here. They must open the bot once for it to work."
            }
            value={telegram}
            onChange={(e) => setTelegram(e.target.value)}
          />
          <Input
            label={editing ? strings.settings.newPassword : strings.auth.passwordLabel}
            // Says what the action does before it is taken: a changed password ends every
            // session that account holds, right now — including your own if it is yours.
            // Before this it ended nothing until the 14-day refresh cookie ran out, which
            // is the whole reason the field is worth explaining.
            hint={editing ? strings.settings.newPasswordHint : undefined}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
      </Modal>
    </Panel>
  );
}
