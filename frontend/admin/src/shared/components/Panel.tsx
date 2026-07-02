import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

function PanelRoot({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx("bg-surface border border-border rounded-lg shadow", className)}
      {...rest}
    />
  );
}

interface PanelHeadProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}

function PanelHead({ title, subtitle, actions, className, children, ...rest }: PanelHeadProps) {
  return (
    <div
      className={clsx(
        "flex items-center justify-between gap-3 px-[18px] py-4 border-b border-border",
        className,
      )}
      {...rest}
    >
      {children ?? (
        <>
          <div className="flex flex-col gap-0.5 min-w-0">
            {title && <h3 className="text-base">{title}</h3>}
            {subtitle && <span className="text-[.78rem] text-text-3 truncate">{subtitle}</span>}
          </div>
          {actions && <div className="flex items-center gap-2 flex-none">{actions}</div>}
        </>
      )}
    </div>
  );
}

function PanelBody({ tight, className, ...rest }: HTMLAttributes<HTMLDivElement> & { tight?: boolean }) {
  return <div className={clsx(tight ? "p-1.5" : "p-[18px]", className)} {...rest} />;
}

export const Panel = Object.assign(PanelRoot, {
  Head: PanelHead,
  Body: PanelBody,
});
