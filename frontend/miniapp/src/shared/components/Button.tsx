import type { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

type Variant = "default" | "primary" | "ghost";
type Size = "md" | "sm";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
  children: ReactNode;
}

const variantClasses: Record<Variant, string> = {
  default: "border-border bg-surface-2 text-text hover:bg-surface hover:border-border-2",
  primary:
    "border-accent bg-accent text-on-accent font-semibold hover:bg-accent-2 hover:border-accent-2",
  ghost: "border-border bg-transparent text-text-2 hover:bg-surface-2 hover:text-text",
};

const sizeClasses: Record<Size, string> = {
  md: "min-h-[42px] px-[15px] text-[13.5px]",
  sm: "min-h-9 px-3 text-[12.5px]",
};

/** Port of the demo's .m-btn / .m-btn-primary / .m-btn-ghost. */
export function Button({
  variant = "default",
  size = "md",
  block,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded border font-body font-medium transition-[background,border-color,transform] duration-150 ease-out active:scale-[.985] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
        variantClasses[variant],
        sizeClasses[size],
        block && "w-full",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
