/**
 * AEGIS-AI — System Status / Connectivity Indicator
 * ====================================================
 * PRD §22: The UI MUST visibly display FULL DATA, DEGRADED MODE, or OFFLINE
 * and tell the operator which feeds are unavailable.
 *
 * Checks:
 *   - Backend API reachability
 *   - Groq AI Gateway status (key configured)
 *   - WebSocket / Socket.IO connectivity
 *   - (optional) individual data feeds via props
 */
import React, { useEffect, useState } from "react";
import { commandApi } from "@/services/api";

// ── Types ─────────────────────────────────────────────────────────────────

type FeedStatus = "ok" | "degraded" | "offline" | "unknown";

interface FeedState {
  name:   string;
  status: FeedStatus;
  note?:  string;
}

export type SystemMode = "FULL_DATA" | "DEGRADED" | "OFFLINE";

// ── Props ─────────────────────────────────────────────────────────────────

interface SystemStatusProps {
  /** Whether Socket.IO WebSocket is connected */
  wsConnected?: boolean;
  /** Whether Groq AI Gateway is available (from /api/command/health) */
  groqOnline?:  boolean;
  /** Groq model name shown in tooltip */
  groqModel?:   string | null;
  /** Extra feed overrides from parent (e.g. from DashboardLayout) */
  extraFeeds?:  FeedState[];
  /** If true, show compact badge only; no dropdown */
  compact?:     boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function deriveMode(feeds: FeedState[]): SystemMode {
  const statuses = feeds.map((f) => f.status);
  if (statuses.every((s) => s === "ok"))      return "FULL_DATA";
  if (statuses.every((s) => s === "offline")) return "OFFLINE";
  return "DEGRADED";
}

const MODE_STYLES: Record<SystemMode, { dot: string; badge: string; label: string }> = {
  FULL_DATA: {
    dot:   "bg-[#38d9c4] shadow-[0_0_8px_#38d9c4]",
    badge: "border-[#38d9c4]/30 bg-[#38d9c4]/10 text-[#38d9c4]",
    label: "FULL DATA",
  },
  DEGRADED: {
    dot:   "bg-[#f3b562] shadow-[0_0_8px_#f3b562]",
    badge: "border-[#f3b562]/30 bg-[#f3b562]/10 text-[#f3b562]",
    label: "DEGRADED",
  },
  OFFLINE: {
    dot:   "bg-[#ff6b6b] shadow-[0_0_8px_#ff6b6b] animate-pulse",
    badge: "border-[#ff6b6b]/30 bg-[#ff6b6b]/10 text-[#ff6b6b]",
    label: "OFFLINE",
  },
};

const STATUS_ICONS: Record<FeedStatus, string> = {
  ok:       "●",
  degraded: "◐",
  offline:  "○",
  unknown:  "?",
};

const STATUS_COLOURS: Record<FeedStatus, string> = {
  ok:       "text-[#38d9c4]",
  degraded: "text-[#f3b562]",
  offline:  "text-[#ff6b6b]",
  unknown:  "text-slate-400",
};

// ── Component ─────────────────────────────────────────────────────────────

export const SystemStatus: React.FC<SystemStatusProps> = ({
  wsConnected,
  groqOnline,
  groqModel,
  extraFeeds = [],
  compact    = false,
}) => {
  const [open,       setOpen]       = useState(false);
  const [apiStatus,  setApiStatus]  = useState<FeedStatus>("unknown");

  // Ping the backend health endpoint
  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        await commandApi.health();
        if (!cancelled) setApiStatus("ok");
      } catch {
        if (!cancelled) setApiStatus("offline");
      }
    };

    check();
    const interval = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Build feed list
  const feeds: FeedState[] = [
    {
      name:   "Backend API",
      status: apiStatus,
      note:   apiStatus === "offline" ? "Start docker-compose to enable" : "FastAPI + Socket.IO",
    },
    {
      name:   "WebSocket (live feed)",
      status: wsConnected === undefined ? "unknown" : wsConnected ? "ok" : "offline",
      note:   wsConnected ? "Real-time updates active" : "Using API polling fallback",
    },
    {
      name:   "Groq AI Gateway",
      status: groqOnline === undefined ? "unknown" : groqOnline ? "ok" : "degraded",
      note:   groqOnline
        ? `Model: ${groqModel ?? "llama-3.3-70b-versatile"}`
        : "Set GROQ_API_KEY in .env — offline fallback active",
    },
    {
      name:   "Decision Engine",
      status: apiStatus === "ok" ? "ok" : "offline",
      note:   "Deterministic priority scorer — always local",
    },
    {
      name:   "Seismic (USGS)",
      status: apiStatus === "ok" ? "ok" : "unknown",
      note:   "Polled every 2 minutes",
    },
    {
      name:   "Weather (Open-Meteo)",
      status: apiStatus === "ok" ? "ok" : "unknown",
      note:   "Polled every 5 minutes",
    },
    ...extraFeeds,
  ];

  const mode   = deriveMode(feeds);
  const styles = MODE_STYLES[mode];

  if (compact) {
    return (
      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-medium ${styles.badge}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${styles.dot}`} />
        {styles.label}
      </span>
    );
  }

  return (
    <div className="relative">
      {/* Badge trigger */}
      <button
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition hover:opacity-80 ${styles.badge}`}
        aria-label="System connectivity status"
      >
        <span className={`h-2 w-2 rounded-full ${styles.dot}`} />
        {styles.label}
      </button>

      {/* Dropdown */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />

          <div className="absolute right-0 top-full z-50 mt-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-[#0d1b2a] shadow-2xl">
            {/* Header */}
            <div className={`flex items-center gap-2 px-4 py-3 ${styles.badge}`}>
              <span className={`h-2 w-2 rounded-full ${styles.dot}`} />
              <span className="text-xs font-bold uppercase tracking-wide">
                System mode: {styles.label}
              </span>
            </div>

            {/* Mode description */}
            {mode === "DEGRADED" && (
              <div className="border-b border-white/10 px-4 py-2 text-xs leading-5 text-[#f3b562]">
                Some data feeds are unavailable. The system will use cached data
                and offline fallbacks where possible.
              </div>
            )}
            {mode === "OFFLINE" && (
              <div className="border-b border-white/10 px-4 py-2 text-xs leading-5 text-[#ff6b6b]">
                Backend is unreachable. Cached map tiles and offline reports only.
                Reconnecting automatically.
              </div>
            )}

            {/* Feed list */}
            <div className="p-2">
              {feeds.map((feed) => (
                <div
                  key={feed.name}
                  className="flex items-start gap-3 rounded-lg px-3 py-2 transition hover:bg-white/[.04]"
                >
                  <span className={`mt-0.5 shrink-0 text-sm ${STATUS_COLOURS[feed.status]}`}>
                    {STATUS_ICONS[feed.status]}
                  </span>
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-slate-200">{feed.name}</div>
                    {feed.note && (
                      <div className="text-[10px] text-slate-500">{feed.note}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="border-t border-white/10 px-4 py-2 text-[10px] text-slate-500">
              Decision Engine is always local and deterministic.
              Groq AI layer is advisory only.
            </div>
          </div>
        </>
      )}
    </div>
  );
};

// ── Standalone compact badge (for use in headers) ─────────────────────────

export const ConnectionBadge: React.FC<{ connected: boolean }> = ({ connected }) => (
  <span
    className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium ${
      connected
        ? "bg-[#38d9c4]/10 text-[#38d9c4]"
        : "bg-[#ff6b6b]/10 text-[#ff6b6b]"
    }`}
  >
    <span
      className={`h-1.5 w-1.5 rounded-full ${
        connected ? "bg-[#38d9c4]" : "bg-[#ff6b6b] animate-pulse"
      }`}
    />
    {connected ? "Online" : "Offline"}
  </span>
);
