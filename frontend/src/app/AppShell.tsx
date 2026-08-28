import { ArrowLeft, MapPin, SunMedium } from "lucide-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAppState } from "./AppState";
import type { MockMode } from "../types";

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode, setMode } = useAppState();
  const isHome = location.pathname === "/";
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link
          className="brand"
          to="/"
          aria-label="Heat-Aware Tourism Guide home"
        >
          <span className="brand-mark">
            <SunMedium size={18} />
          </span>
          <span>Heat-Aware Tourism Guide</span>
        </Link>
      </header>
      {!isHome && (
        <div className="context-bar">
          <button
            className="icon-button"
            type="button"
            onClick={() => navigate(-1)}
            title="Go back"
          >
            <ArrowLeft size={18} />
            <span>Back</span>
          </button>
          <span>
            <MapPin size={15} /> Mock data workspace
          </span>
        </div>
      )}
      <main>
        <Outlet />
      </main>
      {import.meta.env.DEV && !isHome && (
        <aside className="dev-panel" aria-label="Development data state">
          <label htmlFor="mock-state">Preview state</label>
          <select
            id="mock-state"
            value={mode}
            onChange={(event) => setMode(event.target.value as MockMode)}
          >
            <option value="success">Success</option>
            <option value="degraded">Degraded</option>
            <option value="empty">Unavailable</option>
            <option value="error">Error</option>
          </select>
        </aside>
      )}
    </div>
  );
}
