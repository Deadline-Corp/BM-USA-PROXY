import clsx from "clsx";
import { IconChevronRight } from "@/shared/components/icons";

function pillClass(active: boolean) {
  return clsx(
    "relative inline-flex items-center h-8 gap-1.5 pl-3 pr-2 rounded-full border",
    "text-[.78rem] transition-colors duration-150 ease-brand",
    active
      ? "border-accent-line bg-accent/10 text-text"
      : "border-border bg-surface-2 text-text-2 hover:border-text-3",
  );
}

export interface FilterOption {
  value: string;
  label: string;
}

interface FilterPillProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: FilterOption[];
  /** Copy for the empty option — picking it clears the filter. */
  allLabel: string;
}

/** A select styled as a pill, for the filter row above a table.
 *
 * A real `<select>` sits invisibly on top of the pill instead of a hand-rolled dropdown:
 * keyboard, screen readers and the native mobile picker keep working for free. Applied
 * filters are tinted so an operator can tell at a glance which ones are narrowing the list
 * — a filter you forgot you set is how "the payment isn't there" happens.
 */
export function FilterPill({ label, value, onChange, options, allLabel }: FilterPillProps) {
  const active = value !== "";
  const current = options.find((o) => o.value === value)?.label ?? allLabel;

  return (
    <div className={pillClass(active)}>
      <span className="text-text-3">{label}</span>
      <span className="font-medium whitespace-nowrap">{current}</span>
      <IconChevronRight className="w-3 h-3 rotate-90 text-text-3" />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

interface DateFilterPillProps {
  label: string;
  /** ``YYYY-MM-DD``, or empty for no bound. */
  value: string;
  onChange: (value: string) => void;
  /** Copy shown while no date is picked. */
  anyLabel: string;
}

/** The pill above, bound to a date instead of a list — one end of a range. */
export function DateFilterPill({ label, value, onChange, anyLabel }: DateFilterPillProps) {
  const active = value !== "";

  return (
    <div className={pillClass(active)}>
      <span className="text-text-3">{label}</span>
      <span className="font-medium whitespace-nowrap">{active ? value : anyLabel}</span>
      {active ? (
        // Sits above the invisible input so clearing does not reopen the date picker.
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={`Clear ${label}`}
          className="relative z-10 w-4 h-4 grid place-items-center rounded-full text-text-3 hover:text-text hover:bg-surface"
        >
          ×
        </button>
      ) : (
        <IconChevronRight className="w-3 h-3 rotate-90 text-text-3" />
      )}
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
      />
    </div>
  );
}
