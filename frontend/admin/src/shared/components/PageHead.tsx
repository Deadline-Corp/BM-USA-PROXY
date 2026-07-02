import type { ReactNode } from "react";

interface PageHeadProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export function PageHead({ title, subtitle, actions }: PageHeadProps) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap mb-[22px]">
      <div>
        <h1 className="text-[1.563rem]">{title}</h1>
        {subtitle && <p className="text-[.88rem] text-text-2 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2.5">{actions}</div>}
    </div>
  );
}
