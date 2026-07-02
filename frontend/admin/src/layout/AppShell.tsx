import { Outlet } from "react-router-dom";
import { Sidebar } from "@/layout/Sidebar";
import { Topbar } from "@/layout/Topbar";

export function AppShell() {
  return (
    <div className="grid grid-cols-[264px_1fr] min-h-screen">
      <Sidebar />
      <div className="flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 min-w-0">
          <div className="max-w-screen mx-auto px-6 py-[26px] pb-12 animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
