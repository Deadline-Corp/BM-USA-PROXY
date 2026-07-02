import { useCopyToClipboard } from "@/shared/hooks/useCopyToClipboard";
import { IconCheckPlain, IconCopy } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

interface CopyFieldProps {
  value: string;
  label?: string;
  className?: string;
}

export function CopyField({ value, label, className }: CopyFieldProps) {
  const { copied, copy } = useCopyToClipboard();

  return (
    <div className={className}>
      {label && (
        <div className="text-[.68rem] uppercase tracking-[.06em] text-text-3 font-semibold mb-1.5">
          {label}
        </div>
      )}
      <div className="flex items-center gap-2 h-10 pl-3 pr-1.5 bg-surface-2 border border-border rounded-lg">
        <span className="flex-1 min-w-0 font-mono text-[.82rem] text-text truncate">{value}</span>
        <button
          type="button"
          onClick={() => copy(value)}
          aria-label={strings.common.copy}
          className="flex-none w-7 h-7 grid place-items-center rounded-md text-text-3 hover:bg-surface hover:text-accent transition-colors duration-150 ease-brand"
        >
          {copied ? <IconCheckPlain className="w-3.5 h-3.5 text-success" /> : <IconCopy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}
