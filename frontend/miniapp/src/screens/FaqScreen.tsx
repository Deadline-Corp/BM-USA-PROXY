import { useMemo, useState } from "react";
import { HelpCircle, ChevronDown, Send, Plus } from "lucide-react";
import { useFaq } from "../shared/hooks/useFaq";
import { DEFAULT_SUPPORT_URL, useAppLinks } from "../shared/hooks/useLinks";
import { useCreateRequest } from "../shared/hooks/useRequests";
import { useToast } from "../shared/components/Toast";
import { strings } from "../shared/strings";
import { SectionLabel } from "../shared/components/Card";
import { Button } from "../shared/components/Button";
import { Sheet } from "../shared/components/Sheet";
import { AccordionSkeleton } from "../shared/components/Skeleton";
import { ErrorState } from "../shared/components/ErrorState";
import { EmptyState } from "../shared/components/EmptyState";
import type { FaqItem, RequestType } from "../shared/api/types";

function FaqAccordionItem({ item, open, onToggle }: { item: FaqItem; open: boolean; onToggle: () => void }) {
  return (
    <div className={`overflow-hidden rounded border transition-colors duration-[180ms] ease-out ${open ? "border-border-2" : "border-border"} bg-surface`}>
      <button
        type="button"
        className="flex min-h-[56px] w-full items-center gap-3 px-3.5 py-3.5 text-left text-text transition-colors [@media(hover:hover)]:hover:bg-surface-2"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-accent/[.08] text-accent">
          <HelpCircle size={17} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <span className="flex-1 text-[15px] font-semibold leading-snug text-text">{item.question}</span>
        <ChevronDown
          size={16}
          className={`shrink-0 text-text-3 transition-transform duration-200 ease-out ${open ? "rotate-180 text-accent" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <div className="px-3.5 pb-3.5 pl-[58px]">
          <p className="whitespace-pre-line text-[14px] leading-relaxed text-text-2">{item.answer}</p>
        </div>
      ) : null}
    </div>
  );
}

export function FaqScreen() {
  const faqQuery = useFaq();
  const createRequest = useCreateRequest();
  const { showToast } = useToast();
  const linksQuery = useAppLinks();
  const supportUrl = linksQuery.data?.support_url ?? DEFAULT_SUPPORT_URL;

  const [openId, setOpenId] = useState<string | null>(null);
  const [requestSheetOpen, setRequestSheetOpen] = useState(false);
  const [requestType, setRequestType] = useState<RequestType>("support");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const grouped = useMemo(() => {
    const items = faqQuery.data ?? [];
    const map = new Map<string, FaqItem[]>();
    for (const item of items) {
      const list = map.get(item.category) ?? [];
      list.push(item);
      map.set(item.category, list);
    }
    return Array.from(map.entries());
  }, [faqQuery.data]);

  async function handleSubmitRequest() {
    await createRequest.mutateAsync({ type: requestType, subject, body });
    setRequestSheetOpen(false);
    setSubject("");
    setBody("");
    showToast(strings.faq.requestSent);
  }

  return (
    <div className="flex flex-col">
      {/* ── header ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border border-accent/[.14] bg-accent/[.07] text-accent">
          <HelpCircle size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[18px] font-extrabold leading-tight tracking-tight text-text">
            {strings.faq.title}
          </b>
          <span className="text-[13px] text-text-2">{strings.app.tagline}</span>
        </div>
      </div>

      <SectionLabel>{strings.faq.commonQuestions}</SectionLabel>

      {faqQuery.isLoading ? (
        <AccordionSkeleton />
      ) : faqQuery.isError ? (
        <ErrorState message={strings.errors.generic} onRetry={() => faqQuery.refetch()} />
      ) : grouped.length === 0 ? (
        <EmptyState icon={<HelpCircle size={22} strokeWidth={1.5} />} title={strings.faq.empty} />
      ) : (
        <div className="flex flex-col gap-4">
          {grouped.map(([category, items]) => (
            <div key={category} className="flex flex-col gap-1.5">
              <span className="px-0.5 text-[12px] font-semibold uppercase tracking-[.08em] text-text-3">
                {category}
              </span>
              {items.map((item, i) => {
                const id = `${category}-${i}`;
                return (
                  <FaqAccordionItem
                    key={id}
                    item={item}
                    open={openId === id}
                    onToggle={() => setOpenId(openId === id ? null : id)}
                  />
                );
              })}
            </div>
          ))}
        </div>
      )}

      {/* ── contact support ── */}
      <SectionLabel className="mt-5">{strings.faq.contactSupport}</SectionLabel>
      <div className="flex items-center gap-3.5 rounded-lg border border-border/60 bg-surface p-4 shadow-soft">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
          <Send size={20} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[16px] font-bold tracking-tight text-text">
            Still have questions?
          </b>
          <small className="text-[13px] text-text-3">{strings.faq.contactSupportBody}</small>
        </div>
        <a
          href={supportUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="whitespace-nowrap no-underline"
        >
          <Button variant="primary" size="sm">
            {strings.faq.contactSupportCta}
          </Button>
        </a>
      </div>

      {/* ── new request ── */}
      <Button variant="default" block className="mt-3" onClick={() => setRequestSheetOpen(true)}>
        <Plus size={15} aria-hidden="true" />
        {strings.faq.newRequest}
      </Button>

      <Sheet
        open={requestSheetOpen}
        onClose={() => setRequestSheetOpen(false)}
        title={strings.faq.newRequestFormTitle}
        footer={
          <Button
            variant="primary"
            block
            disabled={subject.trim().length === 0 || body.trim().length === 0 || createRequest.isPending}
            onClick={handleSubmitRequest}
          >
            {strings.common.submit}
          </Button>
        }
      >
        <div className="flex flex-col gap-3">
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor="request-type">
              {strings.faq.typeLabel}
            </label>
            <select
              id="request-type"
              className="h-12 w-full rounded border border-border bg-surface-2 px-3 text-[15px] text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
              value={requestType}
              onChange={(e) => setRequestType(e.target.value as RequestType)}
            >
              <option value="support">{strings.faq.typeSupport}</option>
              <option value="reseller">{strings.faq.typeReseller}</option>
              <option value="custom">{strings.faq.typeCustom}</option>
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor="request-subject">
              {strings.faq.subjectLabel}
            </label>
            <input
              id="request-subject"
              className="h-12 w-full rounded border border-border bg-surface-2 px-3 text-[15px] text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor="request-body">
              {strings.faq.bodyLabel}
            </label>
            <textarea
              id="request-body"
              className="min-h-[110px] w-full rounded border border-border bg-surface-2 p-3 text-[15px] text-text focus-visible:border-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>
        </div>
      </Sheet>
    </div>
  );
}
