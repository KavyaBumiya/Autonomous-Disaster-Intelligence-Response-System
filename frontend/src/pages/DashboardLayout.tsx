import React, { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { LiveIncidentsPanel } from "./LiveIncidentsPanel";
import { RecentReportsPanel } from "./RecentReportsPanel";
import { ResourcePanel } from "./ResourceStatusPanel";
import { ZoneDetail } from "./ZoneDetail";

import { zonesApi, type Zone } from "@/services/api";

const CriticalZone3D = lazy(() =>
  import("./CriticalZone3D").then((m) => ({ default: m.CriticalZone3D }))
);
const OperationalMap = lazy(() =>
  import("@/components/OperationalMap").then((m) => ({ default: m.OperationalMap }))
);

const MapFallback = ({ label }: { label: string }) => (
  <div className="ops-panel flex min-h-[380px] items-center justify-center p-6 text-center">
    <div>
      <div className="ops-kicker mb-2">{label}</div>
      <div className="ops-title">Loading map engine…</div>
      <p className="mt-2 text-sm text-slate-400">Mapbox loads only when the map is needed.</p>
    </div>
  </div>
);

interface DashboardLayoutProps {
  initialZoneId?: string;
  children?: React.ReactNode;
}

interface AlertItem {
  type: string;
  message: string;
}

interface SocketLike {
  emit: (event: string, data: unknown) => void;
  on: (event: string, cb: (data: never) => void) => void;
  disconnect: () => void;
  connect?: () => void;
}

interface HeatmapPayload {
  [key: string]: unknown;
}

export const DashboardLayout: React.FC<DashboardLayoutProps> = ({
  initialZoneId,
}) => {
  const navigate = useNavigate();
  const [selectedZone, setSelectedZone] = useState<string | null>(initialZoneId || null);
  const [isConnected, setIsConnected] = useState(false);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const socketRef = useRef<SocketLike | null>(null);

  const pushAlert = (type: string, message: string) => {
    setAlerts((prev) => [{ type, message }, ...prev].slice(0, 5));
  };

  // Connect to WebSocket on mount / zone change
  useEffect(() => {
    const socketAvailable =
      typeof window !== "undefined" &&
      typeof (window as unknown as { io?: unknown }).io === "function";

    if (!socketAvailable) {
      // Offline mode — API polling still works
      return;
    }

    const io = (window as unknown as { io: (opts?: Record<string, unknown>) => SocketLike }).io;
    const socket = io({ transports: ["websocket"] });
    socketRef.current = socket;

    socket.emit("subscribe", { room: "global_feed" });
    if (selectedZone) {
      socket.emit("subscribe", { room: `zone_${selectedZone}` });
    }

    socket.on("connect" as never, (() => {
      setIsConnected(true);
      toast.success("Connected to AegisAI live feed");
    }) as never);

    socket.on("disconnect" as never, (() => {
      setIsConnected(false);
      toast.warning("Disconnected from live feed. Reconnecting...");
      setTimeout(() => socket.connect?.(), 5000);
    }) as never);

    socket.on("new_report" as never, ((data: { payload?: { disaster_type?: string; zone_id?: string } }) => {
      const msg = `New report: ${data.payload?.disaster_type || "unknown"} in zone ${data.payload?.zone_id}`;
      pushAlert("info", msg);
    }) as never);

    socket.on("trust_score_updated" as never, ((data: { payload?: { report_id?: string } }) => {
      pushAlert("warning", `Trust score updated for report ${data.payload?.report_id}`);
    }) as never);

    socket.on("incident_priority_updated" as never, ((data: { payload?: { incident_id?: string; new_priority?: number } }) => {
      pushAlert(
        "critical",
        `Priority updated for incident ${data.payload?.incident_id}: ${data.payload?.new_priority}`
      );
    }) as never);

    socket.on("new_incident" as never, ((data: { payload?: { disaster_type?: string; zone_id?: string } }) => {
      pushAlert(
        "critical",
        `New incident created: ${data.payload?.disaster_type} in zone ${data.payload?.zone_id}`
      );
      if (!selectedZone && data.payload?.zone_id) {
        navigate(`/dashboard/${data.payload.zone_id}`, { replace: true });
      }
    }) as never);

    socket.on("prediction_updated" as never, ((data: { payload?: { zone_id?: string } }) => {
      pushAlert("info", `Prediction updated for zone ${data.payload?.zone_id}`);
    }) as never);

    socket.on("resource_assigned" as never, ((data: { payload?: { action_id?: string } }) => {
      pushAlert("info", `Resource assigned to incident ${data.payload?.action_id}`);
    }) as never);

    socket.on("route_changed" as never, ((data: { payload?: { zone_id?: string } }) => {
      pushAlert("info", `Route changed for zone ${data.payload?.zone_id}`);
    }) as never);

    socket.on("command_interaction" as never, ((data: { data?: { query?: string }; event?: string }) => {
      toast.info(`Command: ${data.data?.query || data.event || "interaction"}`);
    }) as never);

    socket.on("action_state_changed" as never, ((data: {
      action_id?: string;
      new_status?: string;
      changed_by_role?: string;
    }) => {
      const statusLabels: Record<string, string> = {
        approved: "approved",
        rejected: "rejected",
        dispatched: "dispatched",
        completed: "completed",
      };
      const label = statusLabels[data.new_status || ""] || data.new_status;
      pushAlert(
        "info",
        `Action ${data.action_id}: ${label} by ${data.changed_by_role || "system"}`
      );
    }) as never);

    socket.on("resource_status_updated" as never, ((data: {
      resource_id?: string;
      available?: boolean;
      current_load?: number;
      capacity?: number;
    }) => {
      const label = data.available ? "available" : "in use";
      pushAlert(
        "info",
        `Resource ${data.resource_id}: ${label} (load ${data.current_load}/${data.capacity})`
      );
    }) as never);

    return () => {
      socket.disconnect();
      socketRef.current = null;
      setIsConnected(false);
    };
  }, [selectedZone, navigate]);

  // Heatmap state (only meaningful while a zone is selected)
  const [activeHeatmap, setActiveHeatmap] = useState<string | null>(null);
  const [heatmapData, setHeatmapData] = useState<HeatmapPayload | null>(null);

  // Fetch heatmap data when a zone is selected; derive null when no zone
  useEffect(() => {
    if (!selectedZone) return;

    let cancelled = false;

    const fetchHeatmapData = async () => {
      try {
        const res = await axios.get(`/api/heatmaps/combined?zone_id=${selectedZone}`);
        if (!cancelled) {
          setHeatmapData(res.data);
          setActiveHeatmap("combined");
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to fetch heatmap data:", error);
        }
      }
    };

    void fetchHeatmapData();

    return () => {
      cancelled = true;
    };
  }, [selectedZone]);

  const effectiveHeatmapData = selectedZone ? heatmapData : null;
  const effectiveActiveHeatmap = selectedZone ? activeHeatmap : null;

  // Fetch zones from API with priority info
  const { data: zoneResponse, isLoading: loadingZones, error: zonesError } = useQuery<{
    zones: Zone[];
  }>({
    queryKey: ["zones"],
    queryFn: async () => {
      const res = await zonesApi.withPriority();
      return res.data;
    },
    enabled: true,
    refetchInterval: isConnected ? 15000 : 30000,
  });

  const zones = useMemo(() => zoneResponse?.zones ?? [], [zoneResponse]);
  const zonesUnavailable = !loadingZones && zones.length === 0;
  const zoneErrorMessage = axios.isAxiosError(zonesError)
    ? zonesError.response?.status === 401
      ? "Sign in with an operator account to load live zones."
      : "Backend API is offline. Start Docker Desktop and run docker compose up."
    : "No live zones returned from the backend.";

  // Default to first critical zone when nothing selected (derived, not effect)
  const defaultZoneId = useMemo(() => {
    if (zones.length === 0) return null;
    const critical = zones.find(
      (z) => (z.priority_score || 0) > 70 || (z.victim_count || 0) > 0
    );
    return critical?.zone_id ?? zones[0]?.zone_id ?? null;
  }, [zones]);

  const activeZone = selectedZone ?? defaultZoneId;

  // Keep URL in sync when a default zone is chosen
  useEffect(() => {
    if (!selectedZone && defaultZoneId) {
      navigate(`/dashboard/${defaultZoneId}`, { replace: true });
    }
  }, [selectedZone, defaultZoneId, navigate]);

  const headerItems = alerts.map((alert, index) => (
    <div
      key={`${alert.type}-${index}`}
      className={`alert alert-${alert.type} mb-2 px-3 py-2 rounded text-sm`}
    >
      {alert.message}
    </div>
  ));

  return (
    <div className="ops-shell text-white">
      <header className="ops-nav sticky top-0 z-20">
        <div className="ops-container nav-wide flex min-h-[74px] items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#38d9c4] text-lg font-bold text-[#07101c]">A</div>
            <div>
              <div className="text-lg font-bold tracking-tight">AegisAI <span className="font-normal text-slate-400">/ command</span></div>
              <div className="ops-kicker">Autonomous disaster intelligence</div>
            </div>
            <BadgeConnectionStatus isConnected={isConnected} />
          </div>
          <div className="flex items-center gap-2">
            <button className="ops-button" onClick={() => navigate("/command-center")}>Command center</button>
            <button
              className="ops-button"
              onClick={() => setActiveHeatmap((h) => (h === "combined" ? null : "combined"))}
            >
              {effectiveActiveHeatmap === "combined" ? "Hide heatmap" : "Heatmap"}
            </button>
            <AlertsDropdown alerts={alerts} />
            <button className="ops-button-primary rounded-lg px-4 py-2" onClick={() => navigate("/")}>Global feed</button>
          </div>
        </div>
      </header>

      <main className="ops-container py-8">
        <section className="fade-in mb-7 flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <div className="ops-kicker mb-2">Live operations picture / 23 Sep 2026</div>
            <h1 className="max-w-3xl text-3xl font-bold tracking-tight text-white md:text-5xl">See the threat. <span className="text-[#38d9c4]">Move first.</span></h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">A decision surface for incident commanders. Every signal is ranked, explained, and ready for human approval.</p>
          </div>
          <div className="ops-panel flex items-center gap-3 px-4 py-3">
            <span className="h-2.5 w-2.5 rounded-full bg-[#f3b562] shadow-[0_0_14px_#f3b562]" />
            <div>
              <div className="ops-mono text-xs text-slate-300">SYSTEM MODE</div>
              <div className="text-sm font-semibold">{isConnected ? "Live intelligence" : "Offline fallback"}</div>
            </div>
          </div>
        </section>

        <section className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="ops-stat fade-in"><div className="ops-stat-label">Active incidents</div><div className="ops-stat-value">{activeZone ? "03" : "07"}</div><div className="mt-2 text-xs text-[#ff6b6b]">↑ 2 need attention</div></div>
          <div className="ops-stat fade-in"><div className="ops-stat-label">People at risk</div><div className="ops-stat-value">1,284</div><div className="mt-2 text-xs text-[#f3b562]">37 detected in last hour</div></div>
          <div className="ops-stat fade-in"><div className="ops-stat-label">Response readiness</div><div className="ops-stat-value">82%</div><div className="ops-progress mt-2"><span style={{ width: "82%" }} /></div></div>
          <div className="ops-stat fade-in"><div className="ops-stat-label">Actions awaiting approval</div><div className="ops-stat-value text-[#f3b562]">04</div><div className="mt-2 text-xs text-slate-400">Commander review required</div></div>
        </section>

        <section className="ops-panel mb-6 flex flex-col gap-4 p-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="ops-kicker mb-1">Focus area</div>
            <div className="text-sm text-slate-300">Choose an operational zone to filter every signal and recommendation.</div>
          </div>
          <select
            aria-label="Select operational zone"
            value={activeZone || ""}
            onChange={(e) => {
              const zoneId = e.target.value;
              setSelectedZone(zoneId || null);
              socketRef.current?.emit("subscribe", {
                room: zoneId ? `zone_${zoneId}` : "global_feed",
              });
              navigate(`/dashboard/${zoneId || ""}`, { replace: true });
            }}
            className="ops-select min-w-[250px]"
            disabled={loadingZones || zonesUnavailable}
          >
            <option value="">All operational zones</option>
            {zones.map((zone) => (
              <option key={zone.zone_id} value={zone.zone_id}>
                {zone.name || `Zone ${zone.zone_id?.substring(0, 8)}`}
                {zone.priority_score ? ` · ${zone.priority_score}/100` : ""}
              </option>
            ))}
          </select>
          {zonesUnavailable && <div className="mt-2 text-xs text-[#f3b562]">{zoneErrorMessage}</div>}
        </section>

        {alerts.length > 0 && <div className="mb-5">{headerItems}</div>}

        <section className="grid grid-cols-1 gap-6 xl:grid-cols-[280px_minmax(0,1fr)_330px]">
          <div className="space-y-5">
            <LiveIncidentsPanel selectedZone={activeZone} />
            <RecentReportsPanel selectedZone={activeZone} />
            <ResourcePanel zoneId={activeZone} />
          </div>

          <div className="space-y-5">
            <div className="ops-panel ops-glow overflow-hidden">
              <div className="ops-panel-header">
                <div>
                  <div className="ops-kicker">Operational map</div>
                  <div className="ops-title">Threat landscape</div>
                </div>
                <span className="ops-mono text-xs text-slate-400">{effectiveHeatmapData ? "LIVE LAYER" : "SIMULATION"}</span>
              </div>
              <Suspense fallback={<MapFallback label="Operational map" />}>
                <OperationalMap
                  zones={zones}
                  selectedZone={activeZone}
                  onSelectZone={(zoneId) => {
                    setSelectedZone(zoneId);
                    navigate(`/dashboard/${zoneId}`, { replace: true });
                  }}
                />
              </Suspense>
            </div>
            {activeZone ? (
              <ZoneDetail zoneId={activeZone} />
            ) : (
              <div className="ops-panel p-6">
                <div className="ops-kicker mb-2">No zone selected</div>
                <div className="ops-title mb-2">Your next decision starts here.</div>
                <p className="text-sm leading-6 text-slate-400">
                  Select a zone above to open incident reasoning, victim detection, route intelligence, and response actions.
                </p>
              </div>
            )}
          </div>

          <div className="space-y-5">
            <div className="ops-panel p-5">
              <div className="ops-kicker mb-2">Decision queue</div>
              <div className="ops-title mb-4">Human approval gate</div>
              <div className="space-y-3">
                {["Dispatch Team Bravo to Zone A", "Release 70 medical kits", "Open Shelter C overflow"].map((item, index) => (
                  <button
                    key={item}
                    className="flex w-full items-center gap-3 rounded-lg border border-white/10 bg-white/[.03] p-3 text-left transition hover:border-[#38d9c4]/50"
                  >
                    <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold ${index === 0 ? "bg-[#ff6b6b]/20 text-[#ff8b8b]" : "bg-[#f3b562]/20 text-[#f3b562]"}`}>
                      {index + 1}
                    </span>
                    <span className="text-sm text-slate-200">
                      {item}
                      <small className="mt-1 block text-xs text-slate-500">
                        AI confidence {96 - index * 7}% · pending
                      </small>
                    </span>
                  </button>
                ))}
              </div>
              <button className="ops-button-primary mt-4 w-full rounded-lg" onClick={() => navigate("/command-center")}>
                Review queue
              </button>
            </div>
            {activeZone ? (
              <Suspense fallback={<MapFallback label="3D zone view" />}>
                <CriticalZone3D zoneId={activeZone} />
              </Suspense>
            ) : (
              <div className="ops-panel p-5">
                <div className="ops-kicker mb-2">3D zone view</div>
                <div className="ops-title mb-2">Digital twin standby</div>
                <p className="text-sm leading-6 text-slate-400">
                  Select a critical zone to inspect terrain, structures, and rescue routes in 3D.
                </p>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
};

/* Badge for connection status */
const BadgeConnectionStatus: React.FC<{ isConnected: boolean }> = ({ isConnected }) => (
  <span
    className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
      isConnected ? "bg-green-500" : "bg-red-500"
    }`}
  >
    {isConnected ? "Online" : "Offline"}
  </span>
);

/* Alerts Dropdown */
const AlertsDropdown: React.FC<{ alerts: AlertItem[] }> = ({ alerts }) => (
  <div
    className="relative flex items-center gap-1"
    title={alerts[0]?.message || "No new alerts"}
    role="status"
    aria-live="polite"
  >
    <svg className="w-5 h-5 text-yellow-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
      />
    </svg>
    <span className="hidden sm:block sm:ml-2">Alerts</span>
    {alerts.length > 0 && (
      <span className="grid h-5 min-w-5 place-items-center rounded-full bg-[#ff6b6b] px-1 text-[10px] font-bold text-white">
        {alerts.length}
      </span>
    )}
  </div>
);
