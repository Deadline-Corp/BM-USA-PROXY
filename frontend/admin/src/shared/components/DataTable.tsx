import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import type { ColumnDef, OnChangeFn, SortingState } from "@tanstack/react-table";
import type { ReactNode } from "react";
import clsx from "clsx";
import { EmptyState } from "@/shared/components/EmptyState";
import { ErrorState } from "@/shared/components/ErrorState";
import { TableSkeleton } from "@/shared/components/Skeleton";
import { Button } from "@/shared/components/Button";
import {
  IconArrowDown,
  IconArrowUp,
  IconChevronLeft,
  IconChevronRight,
} from "@/shared/components/icons";

interface DataTableProps<T> {
  columns: ColumnDef<T, any>[];
  data: T[];
  total: number;
  limit: number;
  offset: number;
  onOffsetChange: (offset: number) => void;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyHint?: string;
  /** Rendered above the table — search box, select filters, etc. */
  toolbar?: ReactNode;
  getRowId?: (row: T) => string;
  /**
   * Current sort, for screens that sort server-side. Pass this together with
   * `onSortingChange` to make headers clickable; columns then opt out individually with
   * `enableSorting: false`. Omit both and the table behaves exactly as before.
   *
   * Sorting is never done in the browser here: the table only ever holds one page, so
   * client-side sorting would reorder 50 rows and call it "sorted by amount".
   */
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
}

/** The sort direction on a header, including "sortable but not sorted".
 *
 * The idle state is drawn rather than left blank: a header that only sprouts an arrow
 * after you click it gives no hint that clicking does anything.
 */
function SortGlyph({ direction }: { direction: false | "asc" | "desc" }) {
  if (direction === "asc") return <IconArrowUp className="w-3 h-3 text-accent" />;
  if (direction === "desc") return <IconArrowDown className="w-3 h-3 text-accent" />;
  return <IconArrowDown className="w-3 h-3 opacity-30" />;
}

/** Server-side paginated table wrapper around TanStack Table. Every list
 * screen in the app should render its columns through this component so
 * loading/empty/error/pagination states stay identical everywhere. */
export function DataTable<T>({
  columns,
  data,
  total,
  limit,
  offset,
  onOffsetChange,
  isLoading,
  isError,
  onRetry,
  onRowClick,
  emptyTitle,
  emptyHint,
  toolbar,
  getRowId,
  sorting,
  onSortingChange,
}: DataTableProps<T>) {
  const sortable = onSortingChange !== undefined;
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: getRowId as ((row: T) => string) | undefined,
    manualSorting: true,
    enableSorting: sortable,
    // No third "unsorted" click: the server always applies some order, so removing the
    // sort would silently snap back to the default while the header showed no direction.
    enableSortingRemoval: false,
    state: sorting ? { sorting } : {},
    onSortingChange,
  });

  const page = Math.floor(offset / limit) + 1;
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="flex flex-col">
      {toolbar && <div className="p-[18px] border-b border-border">{toolbar}</div>}

      {isError ? (
        <ErrorState onRetry={onRetry} />
      ) : isLoading ? (
        <TableSkeleton cols={columns.length} />
      ) : data.length === 0 ? (
        <EmptyState title={emptyTitle} hint={emptyHint} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[.86rem]">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className="text-left text-[.7rem] uppercase tracking-[.08em] text-text-3 font-semibold px-[14px] py-2.5 border-b border-border whitespace-nowrap"
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 uppercase tracking-[.08em] font-semibold hover:text-text-2 transition-colors duration-150 ease-brand"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <SortGlyph direction={header.column.getIsSorted()} />
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  className={clsx(
                    "transition-colors duration-150 ease-brand border-b border-border last:border-b-0 hover:bg-surface-2",
                    onRowClick && "cursor-pointer",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-[14px] py-3 text-text-2 align-middle">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!isError && !isLoading && total > 0 && (
        <div className="flex items-center justify-between gap-3 px-[18px] py-3 border-t border-border flex-wrap">
          <span className="text-[.78rem] text-text-3">
            <span className="font-mono tabular-nums text-text-2">{from}</span>
            {"–"}
            <span className="font-mono tabular-nums text-text-2">{to}</span> of{" "}
            <span className="font-mono tabular-nums text-text-2">{total}</span>
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onOffsetChange(Math.max(0, offset - limit))}
              disabled={offset === 0}
              aria-label="Previous page"
            >
              <IconChevronLeft />
            </Button>
            <span className="text-[.78rem] text-text-3 font-mono tabular-nums px-1">
              {page} / {pageCount}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onOffsetChange(offset + limit)}
              disabled={offset + limit >= total}
              aria-label="Next page"
            >
              <IconChevronRight />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
