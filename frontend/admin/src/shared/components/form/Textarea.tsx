import { forwardRef } from "react";
import type { TextareaHTMLAttributes } from "react";
import clsx from "clsx";
import { FieldShell } from "@/shared/components/form/FieldShell";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, id, className, rows = 4, ...rest }, ref) => {
    return (
      <FieldShell label={label} error={error} hint={hint} htmlFor={id}>
        <textarea
          ref={ref}
          id={id}
          rows={rows}
          className={clsx(
            "px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-text font-body text-[.88rem] resize-none",
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
Textarea.displayName = "Textarea";
