import { Check, Copy } from "lucide-react";
import clsx from "clsx";
import { useCopyToClipboard } from "../hooks/useCopyToClipboard";
import { strings } from "../strings";

interface CopyFieldProps {
  label: string;
  value: string;
  copyValue?: string;
  masked?: boolean;
  className?: string;
}

/** Label + monospace value + copy button, with a brief "Copied" confirmation. */
export function CopyField({ label, value, copyValue, masked, className }: CopyFieldProps) {
  const { copied, copy } = useCopyToClipboard();

  return (
    <div
      className={clsx(
        "flex items-center gap-0 h-11 overflow-hidden rounded border border-border bg-surface",
        className,
      )}
    >
      <span className="flex h-full w-[58px] shrink-0 items-center border-r border-border bg-surface-2 px-2.5 font-mono text-[10px] uppercase tracking-wide text-text-3">
        {label}
      </span>
      <span className={clsx("num flex-1 overflow-hidden text-ellipsis whitespace-nowrap px-2.5 text-[13px] text-text", masked && "tracking-widest")}>
        {value}
      </span>
      <button
        type="button"
        className="flex h-full w-11 shrink-0 items-center justify-center border-l border-border text-text-3 transition-colors duration-150 ease-out hover:bg-accent/[.08] hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
        aria-label={`Copy ${label}`}
        onClick={() => copy(copyValue ?? value)}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <span className="sr-only" role="status">
        {copied ? strings.common.copied : ""}
      </span>
    </div>
  );
}
