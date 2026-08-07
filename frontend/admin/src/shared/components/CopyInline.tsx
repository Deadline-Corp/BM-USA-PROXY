import clsx from "clsx";
import { useCopyToClipboard } from "@/shared/hooks/useCopyToClipboard";
import { IconCheckPlain, IconCopy } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

interface CopyInlineProps {
  value: string | null | undefined;
  /** Characters kept from the head. The last 4 are always kept too. */
  head?: number;
  className?: string;
}

/** A hash or address shown short inside a table cell, with the full value one click away.
 *
 * A 64-character transaction id cannot sit in a column and leave room for anything else,
 * but the operator's next move is almost always to paste it into a block explorer or a
 * reply to the customer. Selecting truncated text by hand copies the ellipsis, so the
 * button carries the whole value while the cell shows an abbreviation.
 */
export function CopyInline({ value, head = 8, className }: CopyInlineProps) {
  const { copied, copy } = useCopyToClipboard();

  if (!value) return <span className="text-text-3">—</span>;

  // Both ends, not just the head: wallet addresses are commonly recognised by their last
  // characters, and two different payers on the same chain often share a leading prefix.
  const short =
    value.length > head + 6 ? `${value.slice(0, head)}…${value.slice(-4)}` : value;

  return (
    <span className={clsx("inline-flex items-center gap-1", className)}>
      <span className="font-mono text-[.76rem] text-text-2" title={value}>
        {short}
      </span>
      <button
        type="button"
        onClick={(e) => {
          // The shared table supports row clicks; copying must not also open the row.
          e.stopPropagation();
          void copy(value);
        }}
        aria-label={`${strings.common.copy} ${value}`}
        className="flex-none w-5 h-5 grid place-items-center rounded text-text-3 hover:bg-surface hover:text-accent transition-colors duration-150 ease-brand"
      >
        {copied ? (
          <IconCheckPlain className="w-3 h-3 text-success" />
        ) : (
          <IconCopy className="w-3 h-3" />
        )}
      </button>
    </span>
  );
}
