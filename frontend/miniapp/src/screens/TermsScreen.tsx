import { useMemo, useState } from "react";
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
    <div className="flex min-h-screen flex-col bg-app">
      {/* ── header (no tab bar — full-screen gate) ── */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-surface px-4 py-3.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent/[.18] bg-accent/[.09] text-accent">
          <ShieldCheck size={18} strokeWidth={1.5} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <b className="block font-head text-[15px] font-semibold leading-tight tracking-tight text-text">
            {strings.terms.title}
          </b>
          <span className="text-[11.5px] text-text-3">{strings.terms.subtitle}</span>
        </div>
      </div>

      {/* ── scrollable body ── */}
      <div className="scrollbar-thin flex-1 overflow-y-auto px-4 py-4">
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
                      <label className="mb-1.5 block text-xs font-medium text-text-2" htmlFor={`terms-q-${q.id}`}>
                        {q.label}
                        {q.required ? null : ` (${strings.common.optional})`}
                      </label>
                      <input
                        id={`terms-q-${q.id}`}
                        type={q.type === "email" ? "email" : "text"}
                        placeholder={q.type === "email" ? strings.terms.emailPlaceholder : undefined}
                        className={`h-11 w-full rounded border bg-surface-2 px-3 text-sm text-text focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent ${
                          showError ? "border-danger" : "border-border focus-visible:border-accent"
                        }`}
                        value={value}
                        onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                        onBlur={() => setTouched((prev) => ({ ...prev, [q.id]: true }))}
                      />
                      {showError ? (
                        <p className="mt-1 text-[11.5px] text-danger">
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
          disabled={!termsQuery.data || !isValid || acceptTerms.isPending}
          onClick={handleAccept}
        >
          {acceptTerms.isPending ? strings.terms.accepting : strings.terms.accept}
        </Button>
      </div>
    </div>
  );
}
