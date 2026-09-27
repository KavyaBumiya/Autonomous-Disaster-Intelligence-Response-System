/**
 * AEGIS-AI — System Status badge + detail popover
 * Reads shared health store (services/health + useSystemHealth).
 * Overall status is derived by pure rules — not "any failure = DEGRADED".
 */
import React, { useEffect, useState } from "react";
import { useSystemHealth } from "@/hooks/useSystemHealth";
import type { ServiceStatus } from "@/utils/healthStatus";
import { SystemStatusBadge } from "./SystemStatusBadge";
import { SystemStatusPopover } from "./SystemStatusPopover";

interface SystemStatusProps {
  /** Optional Socket.IO connection override for realtime feed */
  wsConnected?: boolean;
  /** Prefer compact badge (still clickable for details) */
  compact?: boolean;
  /** @deprecated retained for call-site compatibility — NVIDIA is tracked in the store */
  aiOnline?: boolean;
  aiModel?: string | null;
}

export type SystemMode = "FULL_DATA" | "DEGRADED" | "OFFLINE";

export const SystemStatus: React.FC<SystemStatusProps> = ({
  wsConnected,
  compact = false,
}) => {
  const [open, setOpen] = useState(false);
  const health = useSystemHealth();
  const { setRealtime, refresh } = health;

  // External socket signal → realtime service status
  useEffect(() => {
    if (wsConnected === undefined) return;
    const next: ServiceStatus = wsConnected ? "ONLINE" : "DEGRADED";
    setRealtime(next);
  }, [wsConnected, setRealtime]);

  const handleRefresh = () => {
    void refresh();
  };

  return (
    <div className="relative">
      <SystemStatusBadge
        overall={health.overall}
        reasons={health.reasons}
        compact={compact}
        expanded={open}
        onClick={() => setOpen((o) => !o)}
      />
      {open && (
        <SystemStatusPopover
          health={{
            api: health.api,
            database: health.database,
            auth: health.auth,
            ai: health.ai,
            predictions: health.predictions,
            maps: health.maps,
            realtime: health.realtime,
            weather: health.weather,
            seismic: health.seismic,
            overall: health.overall,
            reasons: health.reasons,
            aiModel: health.aiModel,
            lastChecked: health.lastChecked,
            checking: health.checking,
          }}
          onClose={() => setOpen(false)}
          onRefresh={handleRefresh}
        />
      )}
    </div>
  );
};

/** Legacy compact online/offline chip (socket only). */
export const ConnectionBadge: React.FC<{ connected: boolean }> = ({ connected }) => (
  <span
    className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium ${
      connected ? "bg-[#38d9c4]/10 text-[#38d9c4]" : "bg-[#ff6b6b]/10 text-[#ff6b6b]"
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
