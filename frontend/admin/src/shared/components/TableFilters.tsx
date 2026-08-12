import type { ReactNode } from "react";
import { IconSearch, IconX } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}

/** The one box a table is searched by.
 *
 * A box per column asks the operator to classify the string in their hand before they can
 * look for it — and they usually can't: an id read off a screenshot, a city, a status, a
 * handle all arrive as "this text". One box over every column removes the guess. The
 * clear button matters more than it looks: a search you forgot you typed is how "the row
 * isn't there" happens.
 */
export function SearchField({ value, onChange, placeholder, className }: SearchFieldProps) {
  return (
    <div className={`relative ${className ?? ""}`}>
      <IconSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-3 pointer-events-none" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full h-10 pl-9 pr-9 bg-surface-2 border border-border rounded-lg text-text font-body text-[.88rem] transition-colors duration-150 ease-brand placeholder:text-text-3 focus:outline-none focus:border-accent-line"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={strings.common.clearSearch}
          className="absolute right-2 top-1/2 -translate-y-1/2 w-6 h-6 grid place-items-center rounded text-text-3 hover:text-text hover:bg-surface"
        >
          <IconX className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

interface FilterBarProps {
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  /** Filter pills — `FilterPill` / `DateFilterPill`. */
  children?: ReactNode;
  /** Whether anything is currently narrowing the list; drives the clear button. */
  isFiltered?: boolean;
  onClear?: () => void;
}

/** Search on top, pills underneath, one way out.
 *
 * The layout is the payments ledger's, lifted out so every table wears the same one. The
 * point is not tidiness: an operator who learns where the search is on one screen should
 * not have to find it again on the next, and a filter that looks different is read as a
 * different thing.
 */
export function FilterBar({
  search,
  onSearchChange,
  searchPlaceholder,
  children,
  isFiltered,
  onClear,
}: FilterBarProps) {
  return (
    <div className="flex flex-col gap-3">
      <SearchField value={search} onChange={onSearchChange} placeholder={searchPlaceholder} />
      {(children || isFiltered) && (
        <div className="flex flex-wrap items-center gap-2">
          {children}
          {isFiltered && onClear && (
            <button
              type="button"
              onClick={onClear}
              className="h-8 px-3 text-[.78rem] text-text-3 hover:text-text transition-colors duration-150 ease-brand"
            >
              {strings.common.clearFilters}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
