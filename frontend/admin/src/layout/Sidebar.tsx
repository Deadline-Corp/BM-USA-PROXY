import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { navGroups } from "@/layout/navConfig";
import { strings } from "@/shared/strings";
import { useAuthStore } from "@/shared/auth/authStore";
import { initials } from "@/shared/lib/format";
import { useDashboardSummary } from "@/shared/hooks/useDashboard";

export function Sidebar() {
  const admin = useAuthStore((s) => s.admin);
  // Pending-requests badge count sourced from the same dashboard summary
  // the Dashboard screen uses — one query, cached, reused here.
  const { data: summary } = useDashboardSummary();

  return (
    <aside className="bg-surface border-r border-border flex flex-col sticky top-0 h-screen overflow-hidden flex-none w-sidebar">
      <div className="flex items-center gap-2.5 px-[18px] pt-[18px] pb-4 border-b border-border">
        <div className="w-9 h-9 flex-none rounded-[10px] bg-accent border border-accent-2 grid place-items-center text-white relative overflow-hidden">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" width={22} height={22}>
            <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
            <path d="M9.5 6.5h5" />
            <path d="M11 18.5h2" />
            <path d="M3 11c0-2.5 1.2-4.5 3-6" />
            <path d="M21 11c0-2.5-1.2-4.5-3-6" />
          </svg>
          <span className="absolute bottom-0 right-0 w-3 h-3 bg-danger rounded-tl-[4px]" />
        </div>
        <div className="min-w-0">
          <div className="font-head font-semibold text-[.98rem] tracking-[-0.01em] text-text truncate">
            {strings.app.name}
          </div>
          <div className="text-[.72rem] text-text-3 mt-px">{strings.app.tagline}</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pt-3.5 pb-2" aria-label="Primary">
        {navGroups.map((group) => (
          <div key={group.label} className="mt-[18px] first:mt-0">
            <div className="text-[.68rem] uppercase tracking-[.12em] text-text-3 font-semibold px-2.5 pb-2">
              {group.label}
            </div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-2.5 w-full min-h-10 px-2.5 py-2 mb-0.5 rounded-lg text-[.9rem] font-medium text-left",
                    "transition-colors duration-150 ease-brand",
                    "[&_svg]:w-[18px] [&_svg]:h-[18px] [&_svg]:flex-none [&_svg]:transition-colors [&_svg]:duration-150 [&_svg]:ease-brand",
                    isActive
                      ? "bg-accent-soft text-accent [&_svg]:text-accent"
                      : "text-text-2 [&_svg]:text-text-3 hover:bg-surface-2 hover:text-text hover:[&_svg]:text-text-2",
                  )
                }
              >
                {item.icon}
                <span className="flex-1">{item.label}</span>
                {item.accessory === "badge" && summary?.new_requests ? (
                  <span className="font-mono tabular-nums text-[.72rem] font-semibold min-w-5 h-5 px-1.5 rounded-full bg-accent text-on-accent grid place-items-center">
                    {summary.new_requests}
                  </span>
                ) : null}
                {item.accessory === "dot" && (
                  <span className="w-[7px] h-[7px] rounded-full bg-accent shadow-[0_0_0_3px_rgba(25,80,121,.09)]" />
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="flex items-center gap-2.5 px-4 py-3.5 border-t border-border">
        <div className="w-9 h-9 flex-none rounded-[10px] bg-surface-2 border border-border-2 grid place-items-center font-mono text-[.78rem] font-semibold text-accent tracking-[.02em]">
          {initials(admin?.display_name)}
        </div>
        <div className="min-w-0">
          <div className="text-[.86rem] font-semibold text-text truncate">{admin?.display_name}</div>
          <div className="text-[.72rem] text-text-3 capitalize">{admin?.role}</div>
        </div>
      </div>
    </aside>
  );
}
