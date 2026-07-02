import { useNavigate } from "react-router-dom";
import { IconSearch } from "@/shared/components/icons";
import { strings } from "@/shared/strings";

export function Topbar() {
  const navigate = useNavigate();

  function onSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      const value = e.currentTarget.value.trim();
      if (value) navigate(`/clients?q=${encodeURIComponent(value)}`);
    }
  }

  return (
    <header className="h-topbar flex-none flex items-center gap-[18px] px-6 border-b border-border bg-[rgba(243,251,255,.92)] backdrop-blur-[8px] sticky top-0 z-20">
      <div className="flex flex-col min-w-0">
        <span className="font-head font-semibold text-[.98rem] tracking-[-0.01em] text-text truncate">
          {strings.app.name}
        </span>
        <span className="text-[.72rem] text-text-3">{strings.app.topbarTagline}</span>
      </div>

      <div className="flex-1 max-w-[440px] relative flex items-center">
        <IconSearch className="absolute left-3 w-4 h-4 text-text-3 pointer-events-none" />
        <input
          type="search"
          placeholder={strings.clients.searchPlaceholder}
          aria-label={strings.common.search}
          onKeyDown={onSearchKeyDown}
          className="w-full h-10 pl-9 pr-3 bg-surface border border-border rounded-xl text-text font-body text-[.88rem] transition-colors duration-150 ease-brand placeholder:text-text-3 focus:outline-none focus:border-accent-line focus:bg-surface-2"
        />
      </div>

      <div className="ml-auto flex items-center gap-3">
        <span className="inline-flex items-center gap-[7px] h-8 px-[11px] rounded-full bg-success-soft border border-success-line text-[.76rem] font-semibold text-text">
          <span className="w-[7px] h-[7px] rounded-full bg-success animate-pulse-live" />
          Live
        </span>
      </div>
    </header>
  );
}
