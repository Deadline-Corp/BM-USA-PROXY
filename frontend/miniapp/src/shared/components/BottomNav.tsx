import { NavLink } from "react-router-dom";
import { Home, LayoutGrid, ShieldCheck, Users, HelpCircle } from "lucide-react";
import clsx from "clsx";
import { strings } from "../strings";

const items = [
  { to: "/", label: strings.nav.home, icon: Home, end: true },
  { to: "/catalog", label: strings.nav.catalog, icon: LayoutGrid, end: false },
  { to: "/access", label: strings.nav.access, icon: ShieldCheck, end: false },
  { to: "/referral", label: strings.nav.referral, icon: Users, end: false },
  { to: "/faq", label: strings.nav.faq, icon: HelpCircle, end: false },
] as const;

/** Port of the demo's .tabbar / .tab — persistent across all screens except Checkout/Terms. */
export function BottomNav() {
  return (
    <nav
      className="flex shrink-0 gap-0 border-t border-border bg-surface px-2 pb-[calc(8px+env(safe-area-inset-bottom,0px))] pt-2"
      role="tablist"
      aria-label="Mini app sections"
    >
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          role="tab"
          className={({ isActive }) =>
            clsx(
              "flex min-h-12 flex-1 flex-col items-center justify-center gap-1 rounded font-body text-[10.5px] font-medium text-text-3 transition-colors duration-150 ease-out hover:text-text-2 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
              isActive && "text-accent",
            )
          }
        >
          {({ isActive }) => (
            <>
              <span
                className={clsx(
                  "flex h-[26px] w-[46px] items-center justify-center rounded-full transition-colors duration-150 ease-out",
                  isActive && "bg-accent/10",
                )}
              >
                <Icon size={20} strokeWidth={1.5} aria-hidden="true" />
              </span>
              {label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
