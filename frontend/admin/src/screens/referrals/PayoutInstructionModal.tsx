import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { usePayoutInstruction } from "@/shared/hooks/useReferrals";
import { useCopyToClipboard } from "@/shared/hooks/useCopyToClipboard";
import { strings } from "@/shared/strings";

/**
 * Send-a-payout helper. The operator scans (or opens) this on a phone wallet and sends;
 * the on-chain watcher then closes the payout itself with the real txid — nothing here is
 * retyped, and nobody has to paste a transaction hash afterwards.
 */
export function PayoutInstructionModal({
  payoutId,
  onClose,
}: {
  payoutId: string | null;
  onClose: () => void;
}) {
  const { data, isLoading, isError, refetch } = usePayoutInstruction(payoutId);
  const { copied, copy } = useCopyToClipboard();
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    if (!data?.qr_payload) {
      setQr(null);
      return;
    }
    let alive = true;
    QRCode.toDataURL(data.qr_payload, { width: 240, margin: 1 })
      .then((url) => alive && setQr(url))
      .catch(() => alive && setQr(null));
    return () => {
      alive = false;
    };
  }, [data?.qr_payload]);

  return (
    <Modal
      open={payoutId !== null}
      onClose={onClose}
      title={strings.referrals.sendPayout}
      footer={
        <Button variant="ghost" onClick={onClose}>
          {strings.common.close}
        </Button>
      }
    >
      {isLoading ? (
        <Skeleton className="h-64" />
      ) : isError || !data ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div className="flex flex-col gap-4">
          {data.status === "paid" ? (
            <div className="flex items-center gap-2">
              <StatusBadge status="paid" />
              <span className="text-[.82rem] text-text-2">
                {strings.referrals.alreadyConfirmed}
              </span>
            </div>
          ) : (
            <p className="text-[.82rem] text-text-2 leading-relaxed">{data.hint}</p>
          )}

          <div className="flex flex-col gap-2.5">
            <Field label={strings.referrals.amountToSend}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[1.05rem] font-semibold text-text tabular-nums">
                  {data.amount} {data.asset}
                </span>
                <Button variant="quiet" size="sm" onClick={() => copy(data.amount)}>
                  {copied ? strings.common.copied : strings.common.copy}
                </Button>
              </div>
            </Field>

            <Field label={strings.referrals.network}>
              <span className="text-[.86rem] text-text">{data.network_label}</span>
            </Field>

            <Field label={strings.referrals.toAddress}>
              <div className="flex items-start gap-2">
                <span className="font-mono text-[.78rem] text-text break-all">
                  {data.to_address}
                </span>
                <Button variant="quiet" size="sm" onClick={() => copy(data.to_address)}>
                  {copied ? strings.common.copied : strings.common.copy}
                </Button>
              </div>
            </Field>
          </div>

          {qr && (
            <div className="flex flex-col items-center gap-2 pt-1">
              <img
                src={qr}
                alt={strings.referrals.qrAlt}
                className="rounded-md border border-border bg-white p-2"
                width={240}
                height={240}
              />
              <span className="text-[.74rem] text-text-3">{strings.referrals.qrHint}</span>
            </div>
          )}

          {data.wallet_uri && (
            <a
              href={data.wallet_uri}
              className="text-[.82rem] text-accent hover:underline text-center"
            >
              {strings.referrals.openInWallet}
            </a>
          )}
        </div>
      )}
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[.72rem] uppercase tracking-wide text-text-3">{label}</span>
      {children}
    </div>
  );
}
