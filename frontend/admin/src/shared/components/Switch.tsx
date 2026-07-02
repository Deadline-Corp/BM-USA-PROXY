import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import clsx from "clsx";

interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  label?: string;
}

export const Switch = forwardRef<HTMLInputElement, SwitchProps>(({ label, className, ...rest }, ref) => {
  return (
    <label className={clsx("relative inline-flex items-center w-[38px] h-[22px] flex-none cursor-pointer group", className)}>
      <input ref={ref} type="checkbox" className="peer absolute opacity-0 w-full h-full z-[2] cursor-pointer m-0" {...rest} />
      <span
        className={clsx(
          "absolute inset-0 rounded-full border transition-colors duration-150 ease-brand",
          "bg-surface-2 border-border-2 peer-checked:bg-accent-soft peer-checked:border-accent-line",
          "peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent peer-focus-visible:outline-offset-2",
        )}
      />
      <span
        className={clsx(
          "absolute top-[3px] left-[3px] w-3.5 h-3.5 rounded-full transition-[transform,background-color] duration-150 ease-brand",
          "bg-text-3 peer-checked:translate-x-4 peer-checked:bg-accent",
        )}
      />
      {label && <span className="sr-only">{label}</span>}
    </label>
  );
});
Switch.displayName = "Switch";
