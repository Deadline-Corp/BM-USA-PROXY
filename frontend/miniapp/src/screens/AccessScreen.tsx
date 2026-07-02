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
};

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
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2 text-text-2">
        <MapPin size={16} strokeWidth={1.5} aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <b className="block truncate text-[13.5px] font-medium text-text">
          {access.city ?? "—"}
          {access.state_code ? `, ${access.state_code}` : ""}
        </b>
        <small className="text-[11.5px] text-text-3">{access.carrier ?? "—"}</small>
      </div>
      <div className="shrink-0 text-right">
        {access.expires_at ? (
          <CountdownBadge expiresAt={access.expires_at} valueClassName="text-[13px] font-medium" />
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
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
          <ShieldCheck size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[15.5px] font-semibold leading-tight tracking-tight text-text">
            {strings.access.title}
          </b>
          <span className="text-xs text-text-3">{strings.app.tagline}</span>
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
            <div className="flex flex-col rounded-lg border border-border bg-surface px-4">
              {accessesQuery.data.active.map((access) => (
                <AccessRow key={access.public_id} access={access} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<Zap size={22} strokeWidth={1.5} />}
              title={strings.access.noAccessTitle}
              body={strings.access.noAccessBody}
              action={
                <>
                  <Link to="/catalog?tariff=trial">
                    <Button variant="primary" size="sm">
                      <Zap size={14} aria-hidden="true" />
                      {strings.access.getFreeTrial}
                    </Button>
                  </Link>
                  <Link to="/catalog">
                    <Button variant="default" size="sm">
                      <List size={14} aria-hidden="true" />
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
              <div className="flex flex-col rounded-lg border border-border bg-surface px-4">
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
