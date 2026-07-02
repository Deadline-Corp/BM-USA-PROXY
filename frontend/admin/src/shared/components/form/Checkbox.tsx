import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import clsx from "clsx";

interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, id, className, ...rest }, ref) => {
    return (
      <label htmlFor={id} className={clsx("inline-flex items-center gap-2 cursor-pointer select-none", className)}>
        <input
          ref={ref}
          id={id}
          type="checkbox"
          className="w-4 h-4 rounded-[4px] border border-border-2 text-accent accent-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          {...rest}
        />
        <span className="text-[.86rem] text-text-2">{label}</span>
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
