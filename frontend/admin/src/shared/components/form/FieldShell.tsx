import type { ReactNode } from "react";

interface FieldShellProps {
  label?: string;
  error?: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}

/** Wraps a single field: label + control + error/hint line. Styled per the
 * prototype's `.field label` token (uppercase, tracked, text-3). */
export function FieldShell({ label, error, hint, children, htmlFor }: FieldShellProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label
          htmlFor={htmlFor}
          className="text-[.74rem] uppercase tracking-[.06em] text-text-3 font-semibold"
        >
          {label}
        </label>
      )}
      {children}
      {error ? (
        <span className="text-[.74rem] text-danger">{error}</span>
      ) : hint ? (
        <span className="text-[.74rem] text-text-3">{hint}</span>
      ) : null}
    </div>
  );
}
