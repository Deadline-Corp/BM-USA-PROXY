import { Link } from "react-router-dom";
import { ShieldCheck, MapPin, ChevronRight, Zap, List } from "lucide-react";
import { useAccesses } from "../shared/hooks/useAccesses";
import { strings } from "../shared/strings";
import { SectionLabel } from "../shared/components/Card";
import { Chip } from "../shared/components/Chip";
import { Button } from "../shared/components/Button";
import { CountdownBadge } from "../shared/components/CountdownBadge";
import { RowListSkeleton } from "../shared/components/Skeleton";
import { ErrorState } from "../shared/components/ErrorState";
import { EmptyState } from "../shared/components/EmptyState";
import type { AccessSummary, AccessStatus } from "../shared/api/types";

const STATUS_TONE: Record<string, "success" | "warn" | "default" | "danger"> = {
  active: "success",
  provisioning: "warn",
  expiring: "warn",
  expired: "default",
  cancelled: "danger",
  revoked: "danger",
  failed: "danger",
};

/** Statuses where the access is over: no countdown, no actions. */
const ENDED_STATUSES = ["revoked", "expired", "failed"];

function statusLabel(status: AccessStatus): string {
  switch (status) {
    case "active":
      return strings.access.statusActive;
    case "expiring":
      return strings.access.statusExpiring;
    case "provisioning":
      return strings.access.statusProvisioning;
    case "expired":
      return strings.access.statusExpired;
    case "cancelled":
      return strings.access.statusCancelled;
    case "revoked":
      return strings.access.statusRevoked;
    case "failed":
      return strings.access.statusFailed;
    default:
      return status;
  }
}

function AccessRow({ access }: { access: AccessSummary }) {
  return (
    <Link
      to={`/access/${access.public_id}`}
      className="flex items-center gap-3 border-b border-border py-3 text-text no-underline last:border-b-0"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
        <MapPin size={17} strokeWidth={1.5} aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <b className="block truncate text-[15px] font-semibold text-text">
          {access.city ?? "—"}
          {access.state_code ? `, ${access.state_code}` : ""}
        </b>
        <small className="text-[12.5px] text-text-3">{access.carrier ?? "—"}</small>
      </div>
      <div className="shrink-0 text-right">
        {/* An ended access keeps its expires_at, so the countdown has to be gated on the
            status rather than on the timestamp — otherwise a revoked row ticks away as
            though it were still live. */}
        {access.expires_at && !ENDED_STATUSES.includes(access.status) ? (
          <CountdownBadge
            expiresAt={access.expires_at}
            variant="remaining"
            valueClassName="text-[14px] font-medium"
          />
        ) : (
          <Chip tone={STATUS_TONE[access.status] ?? "default"}>{statusLabel(access.status)}</Chip>
        )}
      </div>
      <ChevronRight size={15} className="shrink-0 text-text-3" aria-hidden="true" />
    </Link>
  );
}

export function AccessScreen() {
  const accessesQuery = useAccesses();

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border border-accent/[.14] bg-accent/[.07] text-accent">
          <ShieldCheck size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[18px] font-extrabold leading-tight tracking-tight text-text">
            {strings.access.title}
          </b>
          <span className="text-[13px] text-text-2">{strings.app.tagline}</span>
        </div>
      </div>

      {accessesQuery.isLoading ? (
        <>
          <SectionLabel>{strings.access.activeLabel}</SectionLabel>
          <RowListSkeleton count={2} />
        </>
      ) : accessesQuery.isError ? (
        <ErrorState message={strings.errors.generic} onRetry={() => accessesQuery.refetch()} />
      ) : (
        <>
          <SectionLabel>{strings.access.activeLabel}</SectionLabel>
          {accessesQuery.data && accessesQuery.data.active.length > 0 ? (
            <div className="flex flex-col rounded-lg border border-border/60 bg-surface px-4 shadow-soft">
              {accessesQuery.data.active.map((access) => (
                <AccessRow key={access.public_id} access={access} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<Zap size={28} strokeWidth={1.5} />}
              title={strings.access.noAccessTitle}
              body={strings.access.noAccessBody}
              action={
                <>
                  <Link to="/catalog?tariff=trial">
                    <Button variant="cta">
                      <Zap size={16} aria-hidden="true" />
                      {strings.access.getFreeTrial}
                    </Button>
                  </Link>
                  <Link to="/catalog">
                    <Button variant="default">
                      <List size={16} aria-hidden="true" />
                      {strings.access.viewTariffs}
                    </Button>
                  </Link>
                </>
              }
            />
          )}

          {accessesQuery.data && accessesQuery.data.history.length > 0 ? (
            <>
              <SectionLabel className="mt-[18px]">{strings.access.historyLabel}</SectionLabel>
              <div className="flex flex-col rounded-lg border border-border/60 bg-surface px-4 shadow-soft">
                {accessesQuery.data.history.map((access) => (
                  <AccessRow key={access.public_id} access={access} />
                ))}
              </div>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
