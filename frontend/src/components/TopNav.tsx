import React from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { SystemStatus } from "./SystemStatus";
import { Button } from "./ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "▦" },
  { to: "/command", label: "Command", icon: "◈" },
  { to: "/resources", label: "Resources", icon: "⬡" },
  { to: "/predictions", label: "Predictions", icon: "◎" },
  { to: "/heatmaps", label: "Heatmaps", icon: "◍" },
  { to: "/alerts", label: "Alerts", icon: "△" },
];

interface TopNavProps {
  isConnected?: boolean;
  alertCount?: number;
}

export const TopNav: React.FC<TopNavProps> = ({ isConnected, alertCount = 0 }) => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <header className="ops-nav">
      <div className="ops-container nav-wide flex min-h-[64px] items-center justify-between gap-6 py-2">
        <div className="flex items-center gap-4">
          <button
            type="button"
            className="flex items-center gap-3"
            onClick={() => navigate("/dashboard")}
            aria-label="Go to dashboard"
          >
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#38d9c4] text-base font-bold text-[#07101c]">
              A
            </span>
            <span className="hidden text-left sm:block">
              <span className="block text-base font-bold tracking-tight leading-tight">
                AegisAI <span className="font-normal text-slate-400">/ ops</span>
              </span>
              <span className="ops-kicker block text-[10px]">Autonomous disaster intelligence</span>
            </span>
          </button>
          <SystemStatus wsConnected={isConnected} compact />
        </div>

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `ops-nav-link ${isActive ? "active" : ""}`
              }
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <NavLink
            to="/alerts"
            className={({ isActive }) => `ops-nav-link lg:hidden ${isActive ? "active" : ""}`}
            aria-label={`Alerts${alertCount ? `, ${alertCount} unread` : ""}`}
          >
            △
            {alertCount > 0 && (
              <span className="grid h-4 min-w-4 place-items-center rounded-full bg-[#ff6b6b] px-1 text-[10px] font-bold text-white">
                {alertCount}
              </span>
            )}
          </NavLink>
          <Button variant="primary" size="sm" onClick={() => navigate("/command")}>
            Command center
          </Button>
        </div>
      </div>

      {/* Mobile nav row */}
      <div className="ops-container flex gap-1 overflow-x-auto pb-2 lg:hidden" aria-label="Primary mobile">
        {NAV.map((item) => {
          const active = location.pathname.startsWith(item.to);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={`ops-nav-link shrink-0 ${active ? "active" : ""}`}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </NavLink>
          );
        })}
      </div>
    </header>
  );
};
