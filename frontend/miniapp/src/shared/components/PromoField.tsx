import { useEffect, useState } from "react";
import { Tag, X } from "lucide-react";
import { ApiError } from "../api/client";
import { usePromoCheck } from "../hooks/usePromo";
import { formatUsd } from "../lib/format";
import { strings } from "../strings";
import { Num } from "./Num";
import type { PromoQuote } from "../api/types";

interface PromoFieldProps {
  tariffCode: string;
  /** How many are being bought — the discount is a percentage of the whole order. */
  quantity?: number;
  isExtension?: boolean;
  /**
   * Show the money the code saves, not just the percentage. Off where the sheet prices
   * several plans and the buyer has not picked one yet: a discount is a percentage, so it
   * is the same on all of them, but a total is not — quoting one plan's total above a list
   * of five is a number about the wrong purchase.
   */
  totals?: boolean;
  /**
   * Raised whenever the applied quote changes, including to null when the buyer clears it
   * or a re-check refuses it. The parent owns the code it sends with the order: a field
   * that only shows a discount, while the order goes out at full price, is worse than no
   * field at all.
   */
  onChange: (quote: PromoQuote | null) => void;
}

/**
 * "Have a promo code?" — collapsed until asked for.
 *
 * Most buyers do not have one, and an empty text box above the Buy button reads as
 * something they are missing out on. It opens on a tap and takes one line when closed.
 */
export function PromoField({
  tariffCode,
  quantity = 1,
  isExtension = false,
  totals = true,
  onChange,
}: PromoFieldProps) {
  const check = usePromoCheck();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [applied, setApplied] = useState<PromoQuote | null>(null);
  const [error, setError] = useState<string | null>(null);

  const appliedCode = applied?.code ?? null;

  /**
   * Re-price when what is being bought changes.
   *
   * Applying a code on one plan and then switching plan or quantity left the old figure on
   * screen — a discount quoted against a subtotal that no longer exists. The same call
   * that priced it prices it again, and a code that has become invalid in the meantime
   * (an extension-only rule, the last use taken) drops out here rather than at checkout.
   */
  useEffect(() => {
    if (!appliedCode) return;
    let cancelled = false;
    check
      .mutateAsync({ code: appliedCode, tariff_code: tariffCode, quantity, is_extension: isExtension })
      .then((quote) => {
        if (cancelled) return;
        setApplied(quote);
        setError(null);
        onChange(quote);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setApplied(null);
        setError(e instanceof ApiError ? e.message : strings.errors.generic);
        onChange(null);
      });
    return () => {
      cancelled = true;
    };
    // `check` and `onChange` are recreated every render; depending on them would re-quote
    // in a loop. The inputs that actually change the answer are all listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedCode, tariffCode, quantity, isExtension]);

  async function apply() {
    const code = input.trim();
    if (!code) return;
    setError(null);
    try {
      const quote = await check.mutateAsync({
        code,
        tariff_code: tariffCode,
        quantity,
        is_extension: isExtension,
      });
      setApplied(quote);
      onChange(quote);
    } catch (e) {
      setApplied(null);
      onChange(null);
      // The server's own words: "you have already used this promo code" is something the
      // buyer can act on, a generic failure is a message to support.
      setError(e instanceof ApiError ? e.message : strings.errors.generic);
    }
  }

  function clear() {
    setApplied(null);
    setError(null);
    setInput("");
    onChange(null);
  }

  if (applied) {
    return (
      <div className="mb-3 flex items-start gap-2 rounded border border-success/40 bg-success/[.08] px-3.5 py-3">
        <Tag size={14} className="mt-0.5 shrink-0 text-success" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <b className="block text-[14px] font-semibold text-text">
            {applied.code} · −{applied.percent_off}%
          </b>
          {totals ? (
            <p className="mt-0.5 text-[13px] text-text-2">
              <Num className="line-through text-text-3">{formatUsd(applied.subtotal_usd)}</Num>{" "}
              <Num className="font-semibold text-text">{formatUsd(applied.total_usd)}</Num>
            </p>
          ) : (
            <p className="mt-0.5 text-[13px] text-text-2">{strings.promo.appliesToPlan}</p>
          )}
        </div>
        <button
          type="button"
          onClick={clear}
          aria-label={strings.promo.remove}
          className="shrink-0 rounded p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          <X size={15} />
        </button>
      </div>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-accent underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Tag size={13} aria-hidden="true" />
        {strings.promo.prompt}
      </button>
    );
  }

  return (
    <div className="mb-3">
      <label
        htmlFor="promo-code"
        className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-text-3"
      >
        <Tag size={12} className="shrink-0" aria-hidden="true" />
        {strings.promo.label}
      </label>
      <div className="flex gap-2">
        <input
          id="promo-code"
          type="text"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          placeholder={strings.promo.placeholder}
          className="min-w-0 flex-1 rounded border border-border bg-surface px-3.5 py-3 text-[15px] uppercase tracking-wide text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void apply();
            }
          }}
        />
        <button
          type="button"
          onClick={() => void apply()}
          disabled={!input.trim() || check.isPending}
          className="shrink-0 rounded border border-border bg-surface-2 px-3.5 text-[13.5px] font-medium text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          {strings.promo.apply}
        </button>
      </div>
      {error ? <p className="mt-1 text-[12.5px] text-danger">{error}</p> : null}
    </div>
  );
}
