import { forwardRef } from "react";
import type { SelectHTMLAttributes } from "react";
import clsx from "clsx";
import { FieldShell } from "@/shared/components/form/FieldShell";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, hint, id, className, children, ...rest }, ref) => {
    return (
      <FieldShell label={label} error={error} hint={hint} htmlFor={id}>
        <select
          ref={ref}
          id={id}
          className={clsx(
            "h-10 px-3 bg-surface-2 border border-border rounded-lg text-text font-body text-[.88rem]",
            "transition-colors duration-150 ease-brand",
            "focus:outline-none focus:border-accent-line",
            error && "border-danger-line",
            className,
          )}
          {...rest}
        >
          {children}
        </select>
      </FieldShell>
    );
  },
);
Select.displayName = "Select";
