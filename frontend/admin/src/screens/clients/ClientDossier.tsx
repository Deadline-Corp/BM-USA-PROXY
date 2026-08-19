import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
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
import { usePoolLocations } from "@/shared/hooks/usePool";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import clsx from "clsx";

import { IconChevronRight, IconMail, IconPlus } from "@/shared/components/icons";
import { CopyInline } from "@/shared/components/CopyInline";
import { OrderNumber } from "@/shared/components/OrderNumber";
import type { ClientDossier as ClientDossierData, ConversationMessage } from "@/shared/api/types";


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
  const locationsQuery = usePoolLocations();

  const [note, setNote] = useState("");
  const [noteDirty, setNoteDirty] = useState(false);
  const [confirmBan, setConfirmBan] = useState(false);
  const [messageOpen, setMessageOpen] = useState(false);
  const [messageText, setMessageText] = useState("");
  const [issueOpen, setIssueOpen] = useState(false);
  const [issueTariff, setIssueTariff] = useState("");
  const [issueLocationId, setIssueLocationId] = useState("");
  const [issueCarrier, setIssueCarrier] = useState("");

  // Carriers that can actually be issued, narrowed to the chosen city. Sourced from the
  // same availability the city list uses, so the two dropdowns can never describe a
  // combination the allocator would refuse.
  const availableCarriers = useMemo(() => {
    const locations = locationsQuery.data ?? [];
    const scoped = issueLocationId
      ? locations.filter((l) => l.id === issueLocationId)
      : locations;
    const totals = new Map<string, number>();
    for (const loc of scoped) {
      for (const c of loc.carriers) totals.set(c.carrier, (totals.get(c.carrier) ?? 0) + c.free);
    }
    return [...totals]
      .map(([carrier, free]) => ({ carrier, free }))
      .sort((a, b) => a.carrier.localeCompare(b.carrier));
  }, [locationsQuery.data, issueLocationId]);

  // Picking a city can invalidate the carrier chosen before it. Left alone, the form would
  // still submit that pair and the issue would fail on a constraint the operator can no
  // longer see in the list.
  useEffect(() => {
    if (issueCarrier && !availableCarriers.some((c) => c.carrier === issueCarrier)) {
      setIssueCarrier("");
    }
  }, [availableCarriers, issueCarrier]);

  const profile = data?.profile;

  const qc = useQueryClient();
  const lastInboundRef = useRef("");
  useEffect(() => {
    // Fetching a dossier marks that client's inbound messages read server-side, so both the
    // sidebar "unread" badge AND this client's unread mark on the Clients list have to be
    // refreshed to match. Only when the count actually moves, though: the dossier polls now,
    // and firing on every poll would mean an extra dashboard + list request every ten seconds
    // for as long as a panel sits open.
    const inbound = data?.messages?.filter((m) => m.direction === "in").length ?? 0;
    const key = `${clientId}:${inbound}`;
    if (key === lastInboundRef.current) return;
    lastInboundRef.current = key;
    if (inbound > 0) {
      qc.invalidateQueries({ queryKey: ["dashboard", "summary"] });
      qc.invalidateQueries({ queryKey: ["clients"] });
    }
  }, [data, qc, clientId]);

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
      await issueMutation.mutateAsync({
        id: profile.id,
        body: {
          tariff_code: issueTariff,
          // Omitted rather than sent empty: the allocator reads a missing field as "no
          // preference", and an empty string is not a city.
          ...(issueLocationId ? { location_id: issueLocationId } : {}),
          ...(issueCarrier ? { carrier: issueCarrier } : {}),
        },
      });
      toast.success("Access issued");
      setIssueOpen(false);
      setIssueTariff("");
      setIssueLocationId("");
      setIssueCarrier("");
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
        <div className="flex flex-col gap-4">
          <Select
            label="Plan"
            value={issueTariff}
            onChange={(e) => setIssueTariff(e.target.value)}
          >
            <option value="">Select a plan…</option>
            {tariffsQuery.data?.map((t) => (
              <option key={t.id} value={t.code}>
                {t.name} · ${t.price_usd}
              </option>
            ))}
          </Select>
          {/* City and carrier were accepted by the endpoint but had nowhere to be chosen,
              so every operator-issued access took whatever the allocator happened to pick.
              Any means exactly that — no constraint — which is the sane default when the
              customer did not ask for a specific geo.

              Both lists come from what is actually free right now, and the carrier list
              narrows to the chosen city: offering a combination the allocator would refuse
              turns a considered choice into a failed issue with no explanation. The count
              beside each option is how many phones back it. */}
          <div className="grid grid-cols-2 gap-4">
            <Select
              label={strings.clients.issueCity}
              value={issueLocationId}
              onChange={(e) => setIssueLocationId(e.target.value)}
            >
              <option value="">{strings.common.all}</option>
              {locationsQuery.data?.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.state_code ? `${loc.city}, ${loc.state_code}` : loc.city} · {loc.free}
                </option>
              ))}
            </Select>
            <Select
              label={strings.clients.issueCarrier}
              value={issueCarrier}
              onChange={(e) => setIssueCarrier(e.target.value)}
            >
              <option value="">{strings.common.all}</option>
              {availableCarriers.map((c) => (
                <option key={c.carrier} value={c.carrier}>
                  {c.carrier} · {c.free}
                </option>
              ))}
            </Select>
          </div>
        </div>
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

      {/* Conversation */}
      <Section title={strings.clients.dossierConversation}>
        {data.messages.length === 0 ? (
          <EmptyRow text={strings.clients.conversationEmpty} />
        ) : (
          <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3 max-h-[300px] overflow-y-auto">
            {data.messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
          </div>
        )}
      </Section>

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
      <CollapsibleSection
        title={strings.clients.dossierAccesses}
        count={data.accesses.length}
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
                // The connection id belongs on this line because support's next step is
                // opening that phone in the iproxy console. The revoke reason belongs here
                // too — this panel is where "why did this customer lose their proxy" is
                // actually asked, and until now the answer was only in the database.
                sub={[
                  a.carrier ?? "—",
                  a.ip ?? "no IP",
                  a.connection_id ?? "no connection",
                  a.status === "revoked" && a.revoke_reason ? `revoked: ${a.revoke_reason}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
                trailing={<StatusBadge status={a.status} />}
              />
            ))}
          </RowList>
        )}
      </CollapsibleSection>

      {/* Orders */}
      <CollapsibleSection title={strings.clients.dossierOrders} count={data.orders.length}>
        {data.orders.length === 0 ? (
          <EmptyRow text="No orders yet" />
        ) : (
          <RowList>
            {data.orders.map((o) => (
              <RowItem
                key={o.id}
                title={<Num value={o.amount_usd} usd />}
                /* The order number is the only identifier on this panel the customer can
                   quote back, and it is what the orders screen and the resolve dialog both
                   search by — so it is copyable, not just printed. */
                sub={
                  <span className="inline-flex items-center gap-1.5">
                    <OrderNumber value={o.number} />
                    <span>· {o.provider} · {formatDateTime(o.created_at)}</span>
                  </span>
                }
                trailing={<StatusBadge status={o.status} />}
              />
            ))}
          </RowList>
        )}
      </CollapsibleSection>

      {/* Referral */}
      <Section title={strings.clients.dossierReferral}>
        {!data.referral ? (
          <EmptyRow text="Not a referrer" />
        ) : (
          <div className="flex flex-col gap-2">
            {/* The code is here because of what an operator does next with it: paste it into
                the search on Referrals to pull up everything this person has earned and
                every payout they have asked for. */}
            <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2">
              <span className="text-[.78rem] text-text-3">Referral code</span>
              <CopyInline value={data.referral.code} />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <MiniStat label="Link opens" value={data.referral.link_opens} />
              <MiniStat label="Attached" value={data.referral.attached} />
              <MiniStat label="Balance" value={data.referral.balance_usd} usd />
            </div>
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

function MessageBubble({ message }: { message: ConversationMessage }) {
  const outbound = message.direction === "out";
  return (
    <div className={`flex flex-col max-w-[85%] ${outbound ? "self-end items-end" : "self-start items-start"}`}>
      <div
        className={`rounded-lg px-3 py-2 text-[.84rem] leading-snug whitespace-pre-wrap break-words ${
          outbound
            ? "bg-accent text-on-accent"
            : "bg-surface-2 text-text border border-border"
        }`}
      >
        {message.text}
      </div>
      <span className="text-[.66rem] text-text-3 mt-0.5 px-0.5">
        {/* An outbound row with no admin behind it is the bot's automatic
            acknowledgement. Labelling it "Operator" would tell whoever opens this
            thread that a colleague has already answered, and nobody has. */}
        {outbound
          ? (message.admin ?? strings.clients.conversationAuto)
          : strings.clients.conversationClient}
        {" · "}
        {formatDateTime(message.created_at)}
      </span>
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

/** A Section whose list can be folded away, with the item count always visible.
 *
 * A client who has been around a while has a long tail of accesses and orders, and the
 * dossier turned into a scroll. Folded still answers "how many" from the header, so the
 * count is never what the fold hides.
 *
 * Open by default only while the list is short: a couple of rows are worth seeing without
 * a click, a dozen are the reason this exists.
 */
const COLLAPSE_ABOVE = 3;

function CollapsibleSection({
  title,
  count,
  actions,
  children,
}: {
  title: string;
  count: number;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(count <= COLLAPSE_ABOVE);

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex items-center gap-1.5 text-[.72rem] uppercase tracking-[.08em] text-text-3 font-semibold hover:text-text-2"
        >
          <IconChevronRight
            className={clsx("w-3 h-3 transition-transform duration-150 ease-brand", open && "rotate-90")}
          />
          {title}
          <span className="font-mono tabular-nums text-text-3/80">{count}</span>
        </button>
        {actions}
      </div>
      {open && children}
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
