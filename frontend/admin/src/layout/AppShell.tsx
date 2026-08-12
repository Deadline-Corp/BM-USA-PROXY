import { Outlet } from "react-router-dom";
import { Sidebar } from "@/layout/Sidebar";

/** Sidebar plus the page. There is no top bar.
 *
 * It held three things and none of them earned the 64px: the product name and tagline,
 * already in the sidebar two centimetres to the left; a search box that only ever jumped
 * to Clients, which now has its own search along with every other list; and a green
 * "Live" pill wired to nothing at all — it said Live whether or not anything was.
 *
 * `?q=` on /clients still works, so an old link or bookmark lands the same way.
 */
export function AppShell() {
  return (
    <div className="grid grid-cols-[264px_1fr] min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0">
        <div className="max-w-screen mx-auto px-6 py-[26px] pb-12 animate-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
