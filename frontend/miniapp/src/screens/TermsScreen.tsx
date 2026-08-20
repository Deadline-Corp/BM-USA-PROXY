import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { ShieldCheck } from "lucide-react";
import { useTerms, useAcceptTerms } from "../shared/hooks/useTerms";
import { strings } from "../shared/strings";
import { Button } from "../shared/components/Button";
import { ErrorState } from "../shared/components/ErrorState";
import { useToast } from "../shared/components/Toast";
import { ApiError } from "../shared/api/client";
import { consumeReturnTo } from "../shared/auth/termsRedirect";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function TermsScreen() {
  const termsQuery = useTerms();
  const acceptTerms = useAcceptTerms();
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  // Accept unlocks only once the agreement has actually been scrolled through. A consent
  // button you can press without the text having moved is a button people press without
  // reading, which is the whole thing this screen exists to avoid.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [readToEnd, setReadToEnd] = useState(false);

  const checkReadToEnd = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    // A few pixels of slack: sub-pixel heights and the rubber-band bounce on iOS mean the
    // sum lands a fraction short of the bottom often enough to strand people otherwise.
    // Short terms that fit on screen have nothing to scroll and count as read on sight —
    // without that branch the button could never unlock at all.
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= 24) setReadToEnd(true);
  }, []);

  // Only once the agreement itself is in the DOM. Measuring while the loading skeleton was
  // up compared the height of five grey bars against the viewport, decided it all fitted,
  // and unlocked Accept before a word of the terms had been rendered.
  useEffect(() => {
    if (!termsQuery.data) return;
    checkReadToEnd();
  }, [checkReadToEnd, termsQuery.data]);

  const questions = termsQuery.data?.questions ?? [];

  const isValid = useMemo(() => {
    return questions.every((q) => {
      if (!q.required) return true;
      const value = (answers[q.id] ?? "").trim();
      if (value.length === 0) return false;
      if (q.type === "email") return EMAIL_RE.test(value);
      return true;
    });
  }, [questions, answers]);

  async function handleAccept() {
    if (!termsQuery.data || !isValid) return;
    try {
      await acceptTerms.mutateAsync({ version: termsQuery.data.version, answers });
      navigate(consumeReturnTo("/"), { replace: true });
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : strings.errors.generic, "error");
    }
  }

  return (
    <div className="flex h-[var(--tg-vh)] flex-col bg-app">
      {/* ── header (no tab bar — full-screen gate) ── */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-surface px-4 py-3.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-accent/[.14] bg-accent/[.07] text-accent">
          <ShieldCheck size={19} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[17px] font-bold leading-tight tracking-tight text-text">
            {strings.terms.title}
          </b>
          <span className="text-[12.5px] text-text-3">{strings.terms.subtitle}</span>
        </div>
      </div>

      {/* ── scrollable body ── */}
      <div ref={bodyRef} onScroll={checkReadToEnd} className="scrollbar-thin flex-1 overflow-y-auto px-4 py-4">
        {termsQuery.isLoading ? (
          <div className="flex flex-col gap-2">
            <div className="h-4 w-3/4 animate-pulse rounded bg-surface-2" />
            <div className="h-4 w-full animate-pulse rounded bg-surface-2" />
            <div className="h-4 w-5/6 animate-pulse rounded bg-surface-2" />
            <div className="h-4 w-full animate-pulse rounded bg-surface-2" />
            <div className="h-4 w-2/3 animate-pulse rounded bg-surface-2" />
          </div>
        ) : termsQuery.isError || !termsQuery.data ? (
          <ErrorState message={strings.errors.generic} onRetry={() => termsQuery.refetch()} />
        ) : (
          <>
            <div className="prose-terms rounded-lg border border-border bg-surface p-4">
              <ReactMarkdown>{termsQuery.data.text_md}</ReactMarkdown>
            </div>

            {questions.length > 0 ? (
              <div className="mt-4 flex flex-col gap-3">
                {questions.map((q) => {
                  const value = answers[q.id] ?? "";
                  const showError =
                    touched[q.id] && q.required && (value.trim().length === 0 || (q.type === "email" && !EMAIL_RE.test(value)));
                  return (
                    <div key={q.id}>
                      <label className="mb-1.5 block text-[13px] font-medium text-text-2" htmlFor={`terms-q-${q.id}`}>
                        {q.label}
                        {q.required ? null : ` (${strings.common.optional})`}
                      </label>
                      <input
                        id={`terms-q-${q.id}`}
                        type={q.type === "email" ? "email" : "text"}
                        placeholder={q.type === "email" ? strings.terms.emailPlaceholder : undefined}
                        className={`h-12 w-full rounded border bg-surface-2 px-3 text-[15px] text-text focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent ${
                          showError ? "border-danger" : "border-border focus-visible:border-accent"
                        }`}
                        value={value}
                        onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                        onFocus={(e) => {
                          // iOS fires focus before the keyboard has finished animating in,
                          // and the viewport resize that shrinks the page lands after that
                          // again. Wait for both, then put the field back where it can be
                          // seen — the body scrolls, so there is room above the keyboard.
                          const el = e.currentTarget;
                          window.setTimeout(
                            () => el.scrollIntoView({ block: "center", behavior: "smooth" }),
                            350,
                          );
                        }}
                        onBlur={() => setTouched((prev) => ({ ...prev, [q.id]: true }))}
                      />
                      {showError ? (
                        <p className="mt-1 text-[12.5px] text-danger">
                          {q.type === "email" ? strings.terms.emailInvalid : strings.common.required}
                        </p>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </>
        )}
      </div>

      {/* ── sticky accept footer ── */}
      <div className="shrink-0 border-t border-border bg-surface px-4 py-3.5">
        <Button
          variant="primary"
          block
          disabled={!termsQuery.data || !isValid || !readToEnd || acceptTerms.isPending}
          onClick={handleAccept}
        >
          {acceptTerms.isPending ? strings.terms.accepting : strings.terms.accept}
        </Button>
        {/* Without this the disabled button is a dead end with no stated reason — the one
            thing on screen the person came here to press, greyed out and silent. */}
        {termsQuery.data && !readToEnd ? (
          <p className="mt-2 text-center text-[12.5px] text-text-3">{strings.terms.scrollToEnd}</p>
        ) : null}
      </div>
    </div>
  );
}
