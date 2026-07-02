import { useState } from "react";
import { SlideOver } from "@/shared/components/SlideOver";
import { Button } from "@/shared/components/Button";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Num } from "@/shared/components/Num";
import { Skeleton } from "@/shared/components/Skeleton";
import { ErrorState } from "@/shared/components/ErrorState";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Modal } from "@/shared/components/Modal";
import { Textarea } from "@/shared/components/form/Textarea";
import { Select } from "@/shared/components/form/Select";
import { initials } from "@/shared/lib/format";
import { formatDate, formatDateTime } from "@/shared/lib/format";
import {
  useBanClient,
  useClientDossier,
  useIssueAccess,
  useMessageClient,
  useUnbanClient,
  useUpdateClientNote,
} from "@/shared/hooks/useClients";
import { useTariffs } from "@/shared/hooks/useTariffs";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import { IconMail, IconPlus } from "@/shared/components/icons";
import type { ClientDossier as ClientDossierData } from "@/shared/api/types";

interface ClientDossierProps {
  clientId: string | null;
  onClose: () => void;
}

export function ClientDossier({ clientId, onClose }: ClientDossierProps) {
  const toast = useToast();
  const { data, isLoading, isError, refetch } = useClientDossier(clientId);
  const banMutation = useBanClient();
  const unbanMutation = useUnbanClient();
  const noteMutation = useUpdateClientNote();
  const messageMutation = useMessageClient();
  const issueMutation = useIssueAccess();
  const tariffsQuery = useTariffs();

  const [note, setNote] = useState("");
  const [noteDirty, setNoteDirty] = useState(false);
  const [confirmBan, setConfirmBan] = useState(false);
  const [messageOpen, setMessageOpen] = useState(false);
  const [messageText, setMessageText] = useState("");
  const [issueOpen, setIssueOpen] = useState(false);
  const [issueTariff, setIssueTariff] = useState("");

  const profile = data?.profile;

  if (!clientId) return null;

  function resetLocalState() {
    setNote("");
    setNoteDirty(false);
    setMessageText("");
    setIssueTariff("");
  }

  function handleClose() {
    resetLocalState();
    onClose();
  }

  async function handleBanToggle() {
    if (!profile) return;
    try {
      if (profile.banned) {
        await unbanMutation.mutateAsync(profile.id);
        toast.success("Client unbanned");
      } else {
        await banMutation.mutateAsync(profile.id);
        toast.success("Client banned");
      }
      setConfirmBan(false);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleSaveNote() {
    if (!profile) return;
    try {
      await noteMutation.mutateAsync({ id: profile.id, note });
      toast.success(strings.clients.noteSaved);
      setNoteDirty(false);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleSendMessage() {
    if (!profile || !messageText.trim()) return;
    try {
      await messageMutation.mutateAsync({ id: profile.id, text: messageText.trim() });
      toast.success(strings.clients.messageSent);
      setMessageOpen(false);
      setMessageText("");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  async function handleIssueAccess() {
    if (!profile || !issueTariff) return;
    try {
      await issueMutation.mutateAsync({ id: profile.id, body: { tariff_code: issueTariff } });
      toast.success("Access issued");
      setIssueOpen(false);
      setIssueTariff("");
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <>
      <SlideOver
        open={clientId !== null}
        onClose={handleClose}
        title={profile?.display_name || profile?.telegram_username || "Client"}
        subtitle={profile ? `@${profile.telegram_username ?? "—"} · joined ${formatDate(profile.created_at)}` : undefined}
        footer={
          profile && (
            <>
              <Button variant="ghost" size="sm" onClick={() => setMessageOpen(true)}>
                <IconMail />
                {strings.clients.message}
              </Button>
              <Button
                variant={profile.banned ? "primary" : "danger"}
                size="sm"
                onClick={() => setConfirmBan(true)}
              >
                {profile.banned ? strings.clients.unban : strings.clients.ban}
              </Button>
            </>
          )
        }
      >
        {isLoading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-16" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        ) : isError || !data ? (
          <ErrorState onRetry={refetch} />
        ) : (
          <DossierBody
            data={data}
            note={note}
            noteDirty={noteDirty}
            onNoteChange={(v) => {
              setNote(v);
              setNoteDirty(true);
            }}
            onSaveNote={handleSaveNote}
            isSavingNote={noteMutation.isPending}
            onIssueAccessClick={() => setIssueOpen(true)}
          />
        )}
      </SlideOver>

      <ConfirmDialog
        open={confirmBan}
        onClose={() => setConfirmBan(false)}
        onConfirm={handleBanToggle}
        title={profile?.banned ? strings.clients.unban : strings.clients.ban}
        description={profile?.banned ? strings.clients.unbanConfirm : strings.clients.banConfirm}
        confirmLabel={profile?.banned ? strings.clients.unban : strings.clients.ban}
        danger={!profile?.banned}
        isSubmitting={banMutation.isPending || unbanMutation.isPending}
      />

      <Modal
        open={messageOpen}
        onClose={() => setMessageOpen(false)}
        title={strings.clients.message}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMessageOpen(false)}>
              {strings.common.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={handleSendMessage}
              disabled={!messageText.trim()}
              isLoading={messageMutation.isPending}
            >
              {strings.clients.message}
            </Button>
          </>
        }
      >
        <Textarea
          label="Message"
          value={messageText}
          onChange={(e) => setMessageText(e.target.value)}
          placeholder={strings.clients.messagePlaceholder}
          rows={4}
        />
      </Modal>

      <Modal
        open={issueOpen}
        onClose={() => setIssueOpen(false)}
        title={strings.clients.issueAccess}
        footer={
          <>
            <Button variant="ghost" onClick={() => setIssueOpen(false)}>
              {strings.common.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={handleIssueAccess}
              disabled={!issueTariff}
              isLoading={issueMutation.isPending}
            >
              {strings.clients.issueAccess}
            </Button>
          </>
        }
      >
        <Select
          label="Tariff"
          value={issueTariff}
          onChange={(e) => setIssueTariff(e.target.value)}
        >
          <option value="">Select a tariff…</option>
          {tariffsQuery.data?.map((t) => (
            <option key={t.id} value={t.code}>
              {t.name} · ${t.price_usd}
            </option>
          ))}
        </Select>
      </Modal>
    </>
  );
}

/** Renders the dossier body once `data` is confirmed loaded — receiving it
 * as a required prop (rather than reading the outer optional `data`) is
 * what gives TypeScript a clean non-null type here without redundant
 * runtime checks scattered through the JSX below. */
function DossierBody({
  data,
  note,
  noteDirty,
  onNoteChange,
  onSaveNote,
  isSavingNote,
  onIssueAccessClick,
}: {
  data: ClientDossierData;
  note: string;
  noteDirty: boolean;
  onNoteChange: (value: string) => void;
  onSaveNote: () => void;
  isSavingNote: boolean;
  onIssueAccessClick: () => void;
}) {
  const { profile } = data;

  return (
    <div className="flex flex-col gap-6">
      {/* Profile header */}
      <div className="flex items-center gap-3">
        <div className="w-12 h-12 rounded-xl bg-surface-2 border border-border-2 grid place-items-center font-mono text-[.9rem] font-semibold text-accent flex-none">
          {initials(profile.display_name)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[.95rem] font-medium text-text">{profile.display_name ?? "Unnamed client"}</span>
            {profile.banned && <StatusBadge tone="danger" label={strings.clients.banned} />}
            {profile.has_active_access && <StatusBadge tone="success" label={strings.common.active} />}
          </div>
          <div className="font-mono text-[.8rem] text-text-3 mt-0.5">
            {profile.telegram_username ? `@${profile.telegram_username}` : profile.telegram_id}
          </div>
        </div>
      </div>

      {/* TOS */}
      <Section title={strings.clients.dossierTos}>
        <StatusBadge
          tone={data.tos.accepted ? "success" : "neutral"}
          label={
            data.tos.accepted
              ? `Accepted ${data.tos.version ? `v${data.tos.version}` : ""} · ${formatDate(data.tos.accepted_at)}`
              : "Not accepted"
          }
        />
      </Section>

      {/* Note */}
      <Section title={strings.clients.note}>
        <Textarea
          value={noteDirty ? note : profile.operator_note ?? ""}
          onChange={(e) => onNoteChange(e.target.value)}
          rows={3}
          placeholder="Internal note, not visible to the client…"
        />
        {noteDirty && (
          <div className="flex justify-end mt-2">
            <Button size="sm" variant="primary" onClick={onSaveNote} isLoading={isSavingNote}>
              {strings.common.save}
            </Button>
          </div>
        )}
      </Section>

      {/* Accesses */}
      <Section
        title={strings.clients.dossierAccesses}
        actions={
          <Button variant="quiet" size="sm" onClick={onIssueAccessClick}>
            <IconPlus className="w-3.5 h-3.5" />
            {strings.clients.issueAccess}
          </Button>
        }
      >
        {data.accesses.length === 0 ? (
          <EmptyRow text="No accesses yet" />
        ) : (
          <RowList>
            {data.accesses.map((a) => (
              <RowItem
                key={a.id}
                title={`${a.tariff_code} · ${a.city ?? "—"}`}
                sub={`${a.carrier ?? "—"} · ${a.ip ?? "no IP"}`}
                trailing={<StatusBadge status={a.status} />}
              />
            ))}
          </RowList>
        )}
      </Section>

      {/* Orders */}
      <Section title={strings.clients.dossierOrders}>
        {data.orders.length === 0 ? (
          <EmptyRow text="No orders yet" />
        ) : (
          <RowList>
            {data.orders.map((o) => (
              <RowItem
                key={o.id}
                title={<Num value={o.amount_usd} usd />}
                sub={`${o.provider} · ${formatDateTime(o.created_at)}`}
                trailing={<StatusBadge status={o.status} />}
              />
            ))}
          </RowList>
        )}
      </Section>

      {/* Referral */}
      <Section title={strings.clients.dossierReferral}>
        {!data.referral ? (
          <EmptyRow text="Not a referrer" />
        ) : (
          <div className="grid grid-cols-3 gap-2">
            <MiniStat label="Clicks" value={data.referral.clicks} />
            <MiniStat label="Attached" value={data.referral.attached} />
            <MiniStat label="Balance" value={data.referral.balance_usd} usd />
          </div>
        )}
      </Section>

      {/* Requests */}
      <Section title={strings.clients.dossierRequests}>
        {data.requests.length === 0 ? (
          <EmptyRow text="No requests" />
        ) : (
          <RowList>
            {data.requests.map((r) => (
              <RowItem key={r.id} title={r.subject} sub={formatDateTime(r.created_at)} trailing={<StatusBadge status={r.status} />} />
            ))}
          </RowList>
        )}
      </Section>
    </div>
  );
}

function Section({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold">{title}</span>
        {actions}
      </div>
      {children}
    </div>
  );
}

function RowList({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col rounded-lg border border-border overflow-hidden">{children}</div>;
}

function RowItem({ title, sub, trailing }: { title: React.ReactNode; sub: React.ReactNode; trailing?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3.5 py-2.5 border-b border-border last:border-b-0 bg-surface">
      <div className="min-w-0">
        <div className="text-[.86rem] text-text font-medium truncate">{title}</div>
        <div className="text-[.76rem] text-text-3 mt-0.5 truncate">{sub}</div>
      </div>
      {trailing}
    </div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return <div className="text-[.82rem] text-text-3 px-3.5 py-3 border border-dashed border-border rounded-lg">{text}</div>;
}

function MiniStat({ label, value, usd }: { label: string; value: number; usd?: boolean }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2.5 flex flex-col gap-1">
      <span className="text-[.68rem] uppercase tracking-[.06em] text-text-3">{label}</span>
      <Num value={value} usd={usd} className="text-[.92rem] font-semibold text-text" />
    </div>
  );
}
