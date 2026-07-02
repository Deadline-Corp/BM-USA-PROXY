import { useState } from "react";
import { SlideOver } from "@/shared/components/SlideOver";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { CopyField } from "@/shared/components/CopyField";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { Modal } from "@/shared/components/Modal";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Input } from "@/shared/components/form/Input";
import { Textarea } from "@/shared/components/form/Textarea";
import { formatDateTime } from "@/shared/lib/format";
import { useMarkPaidOrder, useOrder, useRefundOrder, useResolveOrder } from "@/shared/hooks/useOrders";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { RequireRole } from "@/shared/auth/RequireRole";

interface OrderDetailProps {
  orderId: string | null;
  onClose: () => void;
}

export function OrderDetail({ orderId, onClose }: OrderDetailProps) {
  const toast = useToast();
  const { data: order, isLoading, isError, refetch } = useOrder(orderId);
  const resolveMutation = useResolveOrder();
  const refundMutation = useRefundOrder();
  const markPaidMutation = useMarkPaidOrder();

  const [refundOpen, setRefundOpen] = useState(false);
  const [refundAmount, setRefundAmount] = useState(0);
  const [refundReason, setRefundReason] = useState("");
  const [refundWallet, setRefundWallet] = useState("");
  const [refundTx, setRefundTx] = useState("");

  const [markPaidOpen, setMarkPaidOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"approve" | "fail" | null>(null);

  if (!orderId) return null;

  async function handleResolve(action: "approve" | "fail") {
    if (!order) return;
    try {
      await resolveMutation.mutateAsync({ id: order.id, body: { action } });
      toast.success(action === "approve" ? "Order approved" : "Order marked failed");
      setConfirmAction(null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleRefund() {
    if (!order) return;
    try {
      await refundMutation.mutateAsync({
        id: order.id,
        body: {
          amount_usd: refundAmount,
          reason: refundReason,
          wallet_address: refundWallet || undefined,
          tx_hash: refundTx || undefined,
        },
      });
      toast.success("Refund recorded");
      setRefundOpen(false);
      setRefundAmount(0);
      setRefundReason("");
      setRefundWallet("");
      setRefundTx("");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleMarkPaid(reason?: string) {
    if (!order) return;
    try {
      await markPaidMutation.mutateAsync({ id: order.id, body: { reason: reason ?? "" } });
      toast.success("Order marked paid");
      setMarkPaidOpen(false);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <>
      <SlideOver
        open={orderId !== null}
        onClose={onClose}
        title={order ? `Order ${order.id.slice(0, 8)}` : "Order"}
        subtitle={order ? `${order.user} · ${order.provider}` : undefined}
        footer={
          order && (
            <>
              {order.status === "manual_review" && (
                <>
                  <Button variant="danger" size="sm" onClick={() => setConfirmAction("fail")}>
                    {strings.orders.fail}
                  </Button>
                  <Button variant="primary" size="sm" onClick={() => setConfirmAction("approve")}>
                    {strings.orders.approve}
                  </Button>
                </>
              )}
              <Button variant="ghost" size="sm" onClick={() => setRefundOpen(true)}>
                {strings.orders.refund}
              </Button>
              <RequireRole role="owner">
                <Button variant="ghost" size="sm" onClick={() => setMarkPaidOpen(true)}>
                  {strings.orders.markPaid}
                </Button>
              </RequireRole>
            </>
          )
        }
      >
        {isLoading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-32" />
          </div>
        ) : isError || !order ? (
          <ErrorState onRetry={refetch} />
        ) : (
          <div className="flex flex-col gap-6">
            <div className="flex items-center justify-between">
              <span className="font-mono tabular-nums text-2xl font-semibold text-text">
                <Num value={order.amount_usd} usd />
              </span>
              <StatusBadge status={order.status} />
            </div>

            {order.invoice && (
              <div>
                <div className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold mb-2">
                  {strings.orders.invoice}
                </div>
                <div className="flex flex-col gap-3">
                  <CopyField label="Invoice ID" value={order.invoice.id} />
                  {order.invoice.wallet_address && (
                    <CopyField label="Wallet address" value={order.invoice.wallet_address} />
                  )}
                  {order.invoice.memo && <CopyField label="Memo" value={order.invoice.memo} />}
                  <div className="text-[.82rem] text-text-2">
                    Currency: <span className="font-mono text-text">{order.invoice.currency}</span>
                  </div>
                </div>
              </div>
            )}

            <div>
              <div className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold mb-2">
                {strings.orders.events}
              </div>
              {!order.events || order.events.length === 0 ? (
                <div className="text-[.82rem] text-text-3 border border-dashed border-border rounded-lg px-3.5 py-3">
                  No events recorded yet.
                </div>
              ) : (
                <div className="flex flex-col">
                  {order.events.map((ev, i) => (
                    <div key={ev.id} className="flex gap-3">
                      <div className="flex flex-col items-center flex-none">
                        <span className="w-2 h-2 rounded-full bg-accent mt-1.5 flex-none" />
                        {i < order.events!.length - 1 && <span className="w-px flex-1 bg-border" />}
                      </div>
                      <div className="pb-4 min-w-0">
                        <div className="text-[.84rem] text-text font-medium">{ev.message}</div>
                        <div className="text-[.74rem] text-text-3 font-mono mt-0.5">{formatDateTime(ev.created_at)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </SlideOver>

      <ConfirmDialog
        open={confirmAction !== null}
        onClose={() => setConfirmAction(null)}
        onConfirm={() => confirmAction && handleResolve(confirmAction)}
        title={confirmAction === "approve" ? strings.orders.approve : strings.orders.fail}
        description={
          confirmAction === "approve"
            ? "Approve this order and activate the client's package?"
            : "Mark this order as failed? The client will not receive access."
        }
        danger={confirmAction === "fail"}
        isSubmitting={resolveMutation.isPending}
      />

      <Modal
        open={refundOpen}
        onClose={() => setRefundOpen(false)}
        title={strings.orders.refund}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRefundOpen(false)}>
              {strings.common.cancel}
            </Button>
            <Button
              variant="danger"
              onClick={handleRefund}
              disabled={refundAmount <= 0 || !refundReason.trim()}
              isLoading={refundMutation.isPending}
            >
              {strings.orders.refund}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            type="number"
            step="0.01"
            min={0}
            label={strings.orders.refundAmount}
            value={refundAmount}
            onChange={(e) => setRefundAmount(Number(e.target.value))}
          />
          <Textarea
            label={strings.common.reason}
            value={refundReason}
            onChange={(e) => setRefundReason(e.target.value)}
            rows={3}
          />
          <Input
            label={strings.orders.walletAddress}
            value={refundWallet}
            onChange={(e) => setRefundWallet(e.target.value)}
          />
          <Input label={strings.orders.txHash} value={refundTx} onChange={(e) => setRefundTx(e.target.value)} />
        </div>
      </Modal>

      <RequireRole role="owner">
        <ConfirmDialog
          open={markPaidOpen}
          onClose={() => setMarkPaidOpen(false)}
          onConfirm={handleMarkPaid}
          title={strings.orders.markPaid}
          description="This manually marks the order paid, bypassing the payment provider. Use only for verified off-system payments."
          confirmLabel={strings.orders.markPaid}
          requireReason
          isSubmitting={markPaidMutation.isPending}
        />
      </RequireRole>
    </>
  );
}
