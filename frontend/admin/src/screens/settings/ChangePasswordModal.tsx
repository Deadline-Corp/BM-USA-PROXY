import { useEffect, useState } from "react";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { PasswordInput } from "@/shared/components/form/PasswordInput";
import { useUpdateAdmin } from "@/shared/hooks/useSystem";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { AdminAccount } from "@/shared/api/types";

const MIN_LENGTH = 10;

/** Sixteen characters from an alphabet with no look-alikes.
 *
 * The password gets read off a screen and typed on a phone, so 0/O and 1/l/I are left out:
 * every one of those is a support message waiting to happen.
 */
function generate(): string {
  const alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint32Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (n) => alphabet[n % alphabet.length]).join("");
}

/** Setting a password, on its own, with the repeat that catches a typo.
 *
 * Separate from the account form because it is a different kind of act: name and handle
 * are edits, this ends every session the account holds the moment it succeeds. Mixing it
 * into the same Save is how somebody changes a display name and signs an operator out
 * without meaning to.
 */
export function ChangePasswordModal({
  admin,
  onClose,
}: {
  admin: AdminAccount | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const updateMutation = useUpdateAdmin();
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (admin) {
      setNext("");
      setRepeat("");
      setError(null);
    }
  }, [admin]);

  const tooShort = next.length > 0 && next.length < MIN_LENGTH;
  const mismatch = repeat.length > 0 && next !== repeat;
  const ready = next.length >= MIN_LENGTH && next === repeat;

  async function save() {
    if (!admin || !ready) return;
    setError(null);
    try {
      await updateMutation.mutateAsync({ id: admin.id, body: { password: next } });
      toast.success(strings.settings.passwordChanged);
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  return (
    <Modal
      open={admin !== null}
      onClose={onClose}
      title={strings.settings.changePassword}
      subtitle={admin ? `${admin.display_name} · ${admin.email}` : undefined}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {strings.common.cancel}
          </Button>
          <Button
            variant="primary"
            onClick={save}
            disabled={!ready}
            isLoading={updateMutation.isPending}
          >
            {strings.common.save}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <PasswordInput
          id="new-password"
          label={strings.settings.newPassword}
          autoFocus
          value={next}
          onChange={setNext}
          hint={strings.settings.newPasswordHint}
          error={tooShort ? strings.settings.passwordTooShort.replace("{min}", String(MIN_LENGTH)) : undefined}
        />
        <PasswordInput
          id="repeat-password"
          label={strings.settings.repeatPassword}
          value={repeat}
          onChange={setRepeat}
          error={mismatch ? strings.settings.passwordsDiffer : undefined}
        />
        <div>
          <button
            type="button"
            className="text-[.8rem] text-accent hover:underline"
            // Fills both boxes and leaves them for you to reveal and copy. This is the
            // answer to "what password do I send them": you see it at the moment you set
            // it, because afterwards nobody can — only the hash is kept.
            onClick={() => {
              const made = generate();
              setNext(made);
              setRepeat(made);
              setError(null);
            }}
          >
            {strings.settings.generatePassword}
          </button>
          <p className="mt-1 text-[.74rem] text-text-3">{strings.settings.passwordNotStored}</p>
        </div>

        {error && (
          <div className="text-[.82rem] text-danger bg-danger-soft border border-danger-line rounded-lg px-3 py-2.5">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
