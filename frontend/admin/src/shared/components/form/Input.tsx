import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import clsx from "clsx";
import { FieldShell } from "@/shared/components/form/FieldShell";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, id, className, ...rest }, ref) => {
    return (
      <FieldShell label={label} error={error} hint={hint} htmlFor={id}>
        <input
          ref={ref}
          id={id}
          className={clsx(
            "h-10 px-3 bg-surface-2 border border-border rounded-lg text-text font-body text-[.88rem]",
            "transition-colors duration-150 ease-brand placeholder:text-text-3",
            "focus:outline-none focus:border-accent-line",
            error && "border-danger-line",
            className,
          )}
          {...rest}
        />
      </FieldShell>
    );
  },
);
Input.displayName = "Input";
