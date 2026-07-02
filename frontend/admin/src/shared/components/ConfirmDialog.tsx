import { useState } from "react";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { strings } from "@/shared/strings";

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (reason?: string) => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  /** Destructive actions render the confirm button in the danger variant. */
  danger?: boolean;
  /** When true, a required reason textarea is shown and its value is
   * passed to onConfirm. */
  requireReason?: boolean;
  isSubmitting?: boolean;
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = strings.common.confirm,
  danger = false,
  requireReason = false,
  isSubmitting = false,
}: ConfirmDialogProps) {
  const [reason, setReason] = useState("");
  const reasonInvalid = requireReason && reason.trim().length === 0;

  function handleClose() {
    setReason("");
    onClose();
  }

  function handleConfirm() {
    if (reasonInvalid) return;
    onConfirm(requireReason ? reason.trim() : undefined);
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={isSubmitting}>
            {strings.common.cancel}
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            onClick={handleConfirm}
            disabled={reasonInvalid || isSubmitting}
            isLoading={isSubmitting}
          >
            {isSubmitting ? strings.common.saving : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {description && <p className="text-[.88rem] text-text-2 leading-relaxed">{description}</p>}
        {requireReason && (
          <div className="flex flex-col gap-1.5">
            <label className="text-[.74rem] uppercase tracking-[.06em] text-text-3 font-semibold">
              {strings.common.reason}
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="w-full px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-text text-[.88rem] font-body resize-none focus:outline-none focus:border-accent-line"
              placeholder={strings.common.reason}
            />
            {reasonInvalid && (
              <span className="text-[.74rem] text-danger">{strings.common.reasonRequired}</span>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
