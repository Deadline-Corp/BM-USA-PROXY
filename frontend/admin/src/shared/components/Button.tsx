import clsx from "clsx";
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "ghost" | "quiet" | "danger";
export type ButtonSize = "default" | "sm";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-2",
  ghost:
    "bg-surface border border-border text-text hover:bg-surface-2 hover:border-border-2",
  quiet: "bg-transparent border border-transparent text-text-2 hover:bg-surface-2 hover:text-text",
  danger: "bg-danger text-on-accent hover:bg-[#a8352f]",
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "min-h-[40px] px-4 text-[.88rem] rounded-xl gap-2",
  sm: "min-h-[32px] px-[11px] text-[.8rem] rounded-lg gap-1.5",
};

/** Shared class builder so <Button> and <LinkButton> render pixel-identical
 * styling — one is a <button>, the other a router <Link>, but the visual
 * language must never drift between them. */
export function buttonClasses(
  variant: ButtonVariant = "ghost",
  size: ButtonSize = "default",
  className?: string,
) {
  return clsx(
    "inline-flex items-center justify-center whitespace-nowrap font-semibold font-body",
    "transition-[background,border-color,color,transform] duration-150 ease-brand",
    "active:translate-y-px disabled:opacity-50 disabled:cursor-not-allowed disabled:active:translate-y-0",
    "[&_svg]:w-4 [&_svg]:h-4",
    variantClasses[variant],
    sizeClasses[size],
    className,
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "ghost", size = "default", isLoading, className, children, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={buttonClasses(variant, size, className)}
        {...rest}
      >
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
