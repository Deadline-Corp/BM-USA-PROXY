import { useQuery } from "@tanstack/react-query";
import { PageHead } from "@/shared/components/PageHead";
import { Panel } from "@/shared/components/Panel";
import { CopyInline } from "@/shared/components/CopyInline";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { EmptyState } from "@/shared/components/EmptyState";
import { Num } from "@/shared/components/Num";
import { walletsApi } from "@/shared/api/endpoints";
import { formatChain, formatNetwork } from "@/shared/lib/format";
import { strings } from "@/shared/strings";
import type { PaymentRail } from "@/shared/api/types";

/** Where customer money lands.
 *
 * One shared receiving address per rail — there is no per-order address, which is why the
 * watcher matches a deposit by its exact amount instead. Read-only by design: these come
 * from ONCHAIN_METHODS in the deploy environment, and an edit box here would be the most
 * valuable field in the console to anyone who got hold of a session.
 */
export function WalletsScreen() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["payment-rails"],
    queryFn: walletsApi.rails,
  });

  return (
    <div>
      <PageHead title={strings.wallets.title} subtitle={strings.wallets.subtitle} />

      {isLoading ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : isError ? (
        <ErrorState onRetry={refetch} />
      ) : data ? (
        <div className="flex flex-col gap-4">
          {/* State first. An address list reads as "money is arriving here" — it is worth
              one line to say whether anything is actually watching these. */}
          <div className="flex flex-wrap items-center gap-2.5 bg-surface border border-border rounded-lg px-[18px] py-3.5">
            <StatusBadge
              tone={data.watching ? "success" : "warning"}
              label={data.watching ? strings.wallets.watching : strings.wallets.notWatching}
            />
            <span className="text-[.8rem] text-text-3">
              {strings.wallets.provider}: <span className="text-text-2 font-mono">{data.provider}</span>
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
          </div>

          {data.error && (
            <div className="bg-danger/[.07] border border-danger-line rounded-lg px-[18px] py-3.5">
              <div className="text-[.86rem] font-semibold text-danger">
                {strings.wallets.configError}
              </div>
              <div className="mt-1 font-mono text-[.8rem] text-text-2">{data.error}</div>
            </div>
          )}

          <Panel>
            <Panel.Head
              title={strings.wallets.accepting}
              subtitle={`${data.configured.length} ${data.configured.length === 1 ? "rail" : "rails"}`}
            />
            <div className="flex flex-col">
              {data.configured.length === 0 ? (
                <EmptyState
                  title={strings.wallets.noneTitle}
                  hint={strings.wallets.noneHint}
                />
              ) : (
                data.configured.map((rail) => <RailRow key={`${rail.asset}-${rail.network}`} rail={rail} />)
              )}
            </div>
          </Panel>

          {data.missing.length > 0 && (
            <Panel>
              <Panel.Head
                title={strings.wallets.notAccepting}
                subtitle={strings.wallets.notAcceptingHint}
              />
              <div className="flex flex-wrap gap-2 p-[18px]">
                {data.missing.map((rail) => (
                  <span
                    key={`${rail.asset}-${rail.network}`}
                    className="inline-flex items-baseline gap-1.5 h-8 px-3 rounded-full border border-border bg-surface-2 text-[.78rem] text-text-2"
                  >
                    <span className="font-semibold text-text">{rail.asset}</span>
                    <span className="text-text-3">
                      {formatChain(rail.chain)} · {formatNetwork(rail.network)}
                    </span>
                  </span>
                ))}
              </div>
            </Panel>
          )}
        </div>
      ) : null}
    </div>
  );
}

function RailRow({ rail }: { rail: PaymentRail }) {
  return (
    <div className="flex items-start gap-4 px-[18px] py-4 border-b border-border last:border-b-0 flex-wrap">
      <div className="min-w-[150px]">
        <div className="text-[.92rem] font-semibold text-text">{rail.asset}</div>
        <div className="text-[.78rem] text-text-3 mt-0.5">
          {formatChain(rail.chain)} · {formatNetwork(rail.network)}
        </div>
      </div>

      <div className="flex-1 min-w-[280px]">
        <div className="text-[.7rem] uppercase tracking-[.06em] text-text-3 font-semibold">
          {strings.wallets.receivingAddress}
        </div>
        <div className="mt-1">
          {/* Full value, not truncated: this is the string an operator reads back to a
              customer, and a shortened one cannot be checked against what they pasted. */}
          <CopyInline value={rail.address} head={rail.address.length} />
        </div>
        {rail.token_contract && (
          <div className="mt-1.5 text-[.74rem] text-text-3">
            {strings.wallets.contract}: <span className="font-mono">{rail.token_contract}</span>
          </div>
        )}
      </div>

      <div className="flex gap-6 flex-none">
        <Fact label={strings.wallets.confirmations} value={<Num value={rail.confirmations} />} />
        <Fact
          label={strings.wallets.minAmount}
          value={rail.min_amount_usd > 0 ? <Num value={rail.min_amount_usd} usd /> : <span className="text-text-3">—</span>}
        />
        <Fact
          label={strings.wallets.tolerance}
          value={rail.tolerance_pct > 0 ? <Num value={rail.tolerance_pct} percent /> : <span className="text-text-3">—</span>}
        />
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-[76px]">
      <div className="text-[.7rem] uppercase tracking-[.06em] text-text-3 font-semibold">{label}</div>
      <div className="mt-1 text-[.9rem] text-text">{value}</div>
    </div>
  );
}
