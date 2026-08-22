import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { walletsApi } from "@/shared/api/endpoints";
import { apiErrorMessage } from "@/shared/api/client";
import { useToast } from "@/shared/components/Toast";
import { formatChain, formatNetwork } from "@/shared/lib/format";
import { strings } from "@/shared/strings";
import type { PaymentRail, PayoutWallet } from "@/shared/api/types";

const railKey = (r: { asset: string; network: string }) => `${r.asset}/${r.network}`;

/** Where customer money lands, and the screen that decides it.
 *
 * Every supported rail is listed, configured or not — one list rather than "accepting"
 * plus a separate "supported but not configured", because an operator who wants to start
 * taking Litecoin should find that switch on the row that says Litecoin. A rail with no
 * address is simply not offered at checkout; clearing an address is how a wallet is
 * removed.
 *
 * Saving here is the most consequential write in the console: from that moment every
 * invoice quotes the new address. Hence the confirm step, which names exactly which rails
 * change and what they change from.
 */
export function WalletsScreen() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["payment-rails"],
    queryFn: walletsApi.rails,
  });

  const [draft, setDraft] = useState<PaymentRail[] | null>(null);
  const [payoutDraft, setPayoutDraft] = useState<PayoutWallet[] | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (data) {
      setDraft(data.rails);
      setPayoutDraft(data.payout_wallets);
    }
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: ({ rails, payouts }: { rails: PaymentRail[]; payouts: PayoutWallet[] }) =>
      walletsApi.saveRails(rails, payouts),
    onSuccess: (saved) => {
      qc.setQueryData(["payment-rails"], saved);
      setDraft(saved.rails);
      setPayoutDraft(saved.payout_wallets);
      toast.success(strings.wallets.saved);
      setConfirming(false);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err));
      setConfirming(false);
    },
  });

  function patch(key: string, changes: Partial<PaymentRail>) {
    setDraft((prev) =>
      prev ? prev.map((r) => (railKey(r) === key ? { ...r, ...changes } : r)) : prev,
    );
  }

  /** Rails grouped by chain, in the order the backend listed them — that order is the
   *  configured one, and re-sorting it here would disagree with every other screen. */
  const railsByChain = useMemo(() => {
    const groups = new Map<string, PaymentRail[]>();
    for (const rail of draft ?? []) {
      const bucket = groups.get(rail.chain);
      if (bucket) bucket.push(rail);
      else groups.set(rail.chain, [rail]);
    }
    return [...groups];
  }, [draft]);

  /** What the confirm dialog reads out: every address about to change, both directions
   *  of the money flow, because both are irreversible once a transfer goes out. */
  const addressChanges = useMemo(() => {
    if (!data || !draft || !payoutDraft) return [];
    const before = new Map(data.rails.map((r) => [railKey(r), r.address]));
    const beforePayout = new Map(data.payout_wallets.map((w) => [w.network, w.address]));
    return [
      ...draft
        .filter((r) => (before.get(railKey(r)) ?? "") !== r.address)
        .map((r) => ({ key: railKey(r), from: before.get(railKey(r)) ?? "", to: r.address })),
      ...payoutDraft
        .filter((w) => (beforePayout.get(w.network) ?? "") !== w.address)
        .map((w) => ({
          key: `payout ${w.network}`,
          from: beforePayout.get(w.network) ?? "",
          to: w.address,
        })),
    ];
  }, [data, draft, payoutDraft]);

  const isDirty = useMemo(() => {
    if (!data || !draft || !payoutDraft) return false;
    return (
      JSON.stringify(data.rails) !== JSON.stringify(draft) ||
      JSON.stringify(data.payout_wallets) !== JSON.stringify(payoutDraft)
    );
  }, [data, draft, payoutDraft]);

  const accepting = draft?.filter((r) => r.address.trim()).length ?? 0;

  return (
    <div>
      <PageHead
        title={strings.wallets.title}
        subtitle={strings.wallets.subtitle}
        actions={
          isDirty && (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (!data) return;
                  setDraft(data.rails);
                  setPayoutDraft(data.payout_wallets);
                }}
              >
                {strings.common.cancel}
              </Button>
              <Button variant="primary" size="sm" onClick={() => setConfirming(true)}>
                {strings.common.save}
              </Button>
            </div>
          )
        }
      />

      {isLoading ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : isError || !data || !draft || !payoutDraft ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2.5 bg-surface border border-border rounded-lg px-[18px] py-3.5">
            <StatusBadge
              tone={data.watching ? "success" : "warning"}
              label={data.watching ? strings.wallets.watching : strings.wallets.notWatching}
            />
            <span className="text-[.8rem] text-text-3">
              {strings.wallets.accepting}:{" "}
              <span className="text-text-2 font-mono">
                {accepting} / {data.supported_count}
              </span>
            </span>
            <span className="text-[.8rem] text-text-3">
              {strings.wallets.chainNetwork}:{" "}
              <span className="text-text-2 font-mono">{data.network}</span>
            </span>
            {!data.watching && (
              <span className="text-[.78rem] text-text-3 basis-full">
                {strings.wallets.notWatchingHint}
              </span>
            )}
            {!data.console_managed && (
              <span className="text-[.78rem] text-text-3 basis-full">
                {strings.wallets.fromEnvHint}
              </span>
            )}
          </div>

          {data.error && (
            <div className="bg-danger/[.07] border border-danger-line rounded-lg px-[18px] py-3.5">
              <div className="text-[.86rem] font-semibold text-danger">
                {strings.wallets.configError}
              </div>
              <div className="mt-1 font-mono text-[.8rem] text-text-2">{data.error}</div>
            </div>
          )}

          {/* Grouped by chain rather than one flat list of twelve. An operator comes here
              with one network in mind ("the Tron address changed"), and a single column of
              USDT/USDC/TRX/BTC/… made them read every row to find the two that mattered.
              The header carries the count that is actually accepting money on that chain,
              so "are we live on Tron" is answered without opening anything. */}
          {railsByChain.map(([chain, rails]) => (
            <Panel key={chain}>
              <Panel.Head
                title={formatChain(chain)}
                subtitle={`${rails.filter((r) => r.address.trim()).length} of ${rails.length} ${strings.wallets.accepting.toLowerCase()}`}
              />
              <div className="flex flex-col">
                {rails.map((rail) => (
                  <RailRow
                    key={railKey(rail)}
                    rail={rail}
                    onChange={(c) => patch(railKey(rail), c)}
                  />
                ))}
              </div>
            </Panel>
          ))}

          {/* The other direction of the money flow. Down here on purpose: it is read far
              less often than the receiving addresses, and mixing the two lists would
              invite pasting a payout wallet into a receiving rail. */}
          <Panel>
            <Panel.Head
              title={strings.wallets.payoutTitle}
              subtitle={strings.wallets.payoutHint}
            />
            <div className="flex flex-col">
              {payoutDraft.map((w) => (
                <div
                  key={w.network}
                  className="px-[18px] py-4 border-b border-border last:border-b-0 flex items-end gap-3 flex-wrap"
                >
                  <div className="min-w-[210px]">
                    <div className="text-[.92rem] font-semibold text-text">{w.label}</div>
                    <div className="text-[.78rem] text-text-3 mt-0.5">
                      {formatChain(w.chain)} · {formatNetwork(w.network)}
                    </div>
                  </div>
                  <div className="w-[420px] max-w-full">
                    <Input
                      value={w.address}
                      onChange={(e) =>
                        setPayoutDraft((prev) =>
                          prev
                            ? prev.map((x) =>
                                x.network === w.network ? { ...x, address: e.target.value } : x,
                              )
                            : prev,
                        )
                      }
                      placeholder={strings.wallets.payoutPlaceholder}
                      aria-label={`Payout address for ${w.network}`}
                      className="w-full font-mono text-[.82rem]"
                      size={1}
                    />
                  </div>
                  <StatusBadge
                    tone={w.address.trim() ? "success" : "neutral"}
                    label={w.address.trim() ? strings.wallets.payoutOn : strings.wallets.payoutOff}
                  />
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={() =>
          draft && payoutDraft && saveMutation.mutate({ rails: draft, payouts: payoutDraft })
        }
        title={strings.wallets.confirmTitle}
        description={
          addressChanges.length === 0
            ? strings.wallets.confirmNoAddressChange
            : `${strings.wallets.confirmAddressChange}\n\n` +
              addressChanges
                .map((c) => `${c.key}: ${c.from || "—"} → ${c.to || "—"}`)
                .join("\n")
        }
        confirmLabel={strings.common.save}
        danger={addressChanges.length > 0}
        isSubmitting={saveMutation.isPending}
      />
    </div>
  );
}

function RailRow({
  rail,
  onChange,
}: {
  rail: PaymentRail;
  onChange: (changes: Partial<PaymentRail>) => void;
}) {
  const on = Boolean(rail.address.trim());
  return (
    <div className="px-[18px] py-4 border-b border-border last:border-b-0">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="min-w-[170px]">
          <div className="text-[.92rem] font-semibold text-text">{rail.asset}</div>
          <div className="text-[.78rem] text-text-3 mt-0.5">
            {formatChain(rail.chain)} · {formatNetwork(rail.network)}
          </div>
        </div>
        <StatusBadge
          tone={on ? "success" : "neutral"}
          label={on ? strings.wallets.railOn : strings.wallets.railOff}
        />
        {rail.token_contract && (
          <span className="text-[.72rem] text-text-3 font-mono truncate max-w-[280px]">
            {strings.wallets.contract}: {rail.token_contract}
          </span>
        )}
      </div>

      <div className="mt-3 flex items-end gap-3 flex-wrap">
        <div className="flex-1 min-w-[320px]">
          <Input
            label={strings.wallets.receivingAddress}
            value={rail.address}
            onChange={(e) => onChange({ address: e.target.value })}
            placeholder={strings.wallets.addressPlaceholder}
            className="w-full font-mono text-[.82rem]"
            size={1}
          />
        </div>
        <div className="w-[110px]">
          <Input
            label={strings.wallets.confirmations}
            type="number"
            min={0}
            value={rail.confirmations}
            onChange={(e) => onChange({ confirmations: Number(e.target.value) })}
            className="w-full"
            size={1}
          />
        </div>
      </div>
    </div>
  );
}
