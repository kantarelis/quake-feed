import { NavLink, Outlet } from "react-router";

import { RequireApiKey } from "./RequireApiKey";
import { SettingsPanel } from "./SettingsPanel";

function navLinkClass({ isActive }: { isActive: boolean }): string {
  const base = "text-sm transition-colors";
  return isActive
    ? `${base} font-semibold text-slate-900`
    : `${base} text-slate-500 hover:text-slate-900`;
}

/** App chrome: header (title + nav + settings) and the gated routed content. */
export function Layout() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <span className="text-lg font-semibold tracking-tight">quake-feed</span>
          <nav className="flex gap-4">
            <NavLink to="/" end className={navLinkClass}>
              Map
            </NavLink>
            <NavLink to="/recent" className={navLinkClass}>
              Recent
            </NavLink>
            <NavLink to="/alerts" className={navLinkClass}>
              Alerts
            </NavLink>
          </nav>
          <SettingsPanel />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        <RequireApiKey>
          <Outlet />
        </RequireApiKey>
      </main>
    </div>
  );
}
