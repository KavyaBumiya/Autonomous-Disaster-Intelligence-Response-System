import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { LiveIncidentsPanel } from "./LiveIncidentsPanel";
import { RecentReportsPanel } from "./RecentReportsPanel";
import { ResourcePanel } from "./ResourceStatusPanel";
import { ZoneDetail } from "./ZoneDetail";
import { CriticalZone3D } from "./CriticalZone3D";
import { OperationalMap } from "@/components/OperationalMap";

import { useWebSocket } from "@/hooks/useWebSocket";
import { zonesApi } from "@/services/api";

interface DashboardLayoutProps {
  initialZoneId?: string;
  children?: React.ReactNode;
}

export const DashboardLayout: React.FC<DashboardLayoutProps> = ({
  initialZoneId,
}) => {
  const navigate = useNavigate();
  const [selectedZone, setSelectedZone] = useState<string | null>(initialZoneId || null);
  const [isConnected, setIsConnected] = useState(false);
  const [alerts, setAlerts] = useState<{ type: string; message: string }[]>([]);

  // Keep socket in a ref so it's accessible outside the useEffect (e.g. in onChange)
  const socketRef = useRef<any>(null);

  // Connect to WebSocket on mount
  useEffect(() => {
    // Check if Socket.IO is available (requires backend server running)
    const socketAvailable = typeof window !== "undefined" && typeof (window as any).io === "function";

    if (!socketAvailable) {
      // Socket.IO not available - UI will work in offline mode using API polling
      setIsConnected(false);
      if (typeof window !== "undefined") {
        toast.info("Socket.IO not available - running in offline mode. Using API polling.");
      }
      return; // Exit early - UI will function without real-time updates
    }

    const socket = typeof window !== "undefined" ? (window as any).io({ transports: ["websocket"] }) : null;
    socketRef.current = socket;

    if (socket) {
      // Subscribe to global feed first
      socket.emit("subscribe", { room: "global_feed" });

      // If a zone is selected, subscribe to that zone room
      if (selectedZone) {
        socket.emit("subscribe", { room: `zone_${selectedZone}` });
      }

      socket.on("connect", () => {
        setIsConnected(true);
        toast.success("Connected to AegisAI live feed");
      });

      socket.on("disconnect", () => {
        setIsConnected(false);
        toast.warning("Disconnected from live feed. Reconnecting...");
        setTimeout(() => socket.connect(), 5000);
      });

      // Handle all Phase 1 event types
      socket.on("new_report", (data: any) => {
        const msg = `New report: ${data.payload.disaster_type || "unknown"} in zone ${data.payload.zone_id}`;
        setAlerts((prev) => [{ type: "info", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("trust_score_updated", (data: any) => {
        const msg = `Trust score updated for report ${data.payload.report_id}`;
        setAlerts((prev) => [{ type: "warning", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("incident_priority_updated", (data: any) => {
        const msg = `Priority updated for incident ${data.payload.incident_id}: ${data.payload.new_priority}`;
        setAlerts((prev) => [{ type: "critical", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("new_incident", (data: any) => {
        const msg = `New incident created: ${data.payload.disaster_type} in zone ${data.payload.zone_id}`;
        setAlerts((prev) => [{ type: "critical", message: msg }, ...prev].slice(0, 5));
        if (!selectedZone) {
          navigate(`/dashboard/${data.payload.zone_id}`, { replace: true });
        }
      });

      socket.on("prediction_updated", (data: any) => {
        const msg = `Prediction updated for zone ${data.payload.zone_id}`;
        setAlerts((prev) => [{ type: "info", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("resource_assigned", (data: any) => {
        const msg = `Resource assigned to incident ${data.payload.action_id}`;
        setAlerts((prev) => [{ type: "info", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("route_changed", (data: any) => {
        const msg = `Route changed for zone ${data.payload.zone_id}`;
        setAlerts((prev) => [{ type: "info", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("command_interaction", (data: any) => {
        // Handle command center interactions
        console.log("Command interaction:", data);
        toast.info(`Command: ${data.data?.query || data.event || "interaction"}`);
      });

      socket.on("action_state_changed", (data: any) => {
        const { action_id, new_status, changed_by_role } = data;
        const status_labels: Record<string, string> = {
          approved: "approved",
          rejected: "rejected",
          dispatched: "dispatched",
          completed: "completed",
        };
        const label = status_labels[new_status] || new_status;
        const msg = `Action ${action_id}: ${label} by ${changed_by_role || "system"}`;
        setAlerts((prev) => [{ type: "info", message: msg }, ...prev].slice(0, 5));
      });

      socket.on("resource_status_updated", (data: any) => {
        const { resource_id, available, current_load, capacity } = data;
        const label = available ? "available" : "in use";
        const msg = `Resource ${resource_id}: ${label} (load ${current_load}/${capacity})`;
        setAlerts((prev) => [{ type: "info", message: msg }, ...prev].slice(0, 5));
      });

      return () => {
        socket.disconnect();
        socketRef.current = null;
      };
    }
  }, [selectedZone]);

  // Keep socket in a ref so it's accessible outside the useEffect (e.g. in onChange)
  // socketRef is already declared above

  // Heatmap state
  const [activeHeatmap, setActiveHeatmap] = useState<string | null>(null);
  const [heatmapData, setHeatmapData] = useState<any>(null);

  // Fetch heatmap data from API
  useEffect(() => {
    if (!selectedZone) return;

    const fetchHeatmapData = async () => {
      try {
        const res = await axios.get(`/api/heatmaps/combined?zone_id=${selectedZone}`);
        setHeatmapData(res.data);
        setActiveHeatmap("combined");
      } catch (error) {
        console.error("Failed to fetch heatmap data:", error);
        setActiveHeatmap(null);
      }
    };

    fetchHeatmapData();

    // Cleanup function
    return () => {
      setActiveHeatmap(null);
      setHeatmapData(null);
    };
  }, [selectedZone]);

  // Keep socket in a ref so it's accessible outside the useEffect (e.g. in onChange)
  // socketRef is already declared above

  // Fetch zones from API with priority info
  const { data: zoneResponse, isLoading: loadingZones, error: zonesError } = useQuery<{ zones: any[] }>({
    queryKey: ["zones"],
    queryFn: async () => {
      const res = await zonesApi.withPriority();
      return res.data;
    },
    enabled: true,
    refetchInterval: isConnected ? 15000 : 30000,
  });
  const zones = zoneResponse?.zones ?? [];
  const zonesUnavailable = !loadingZones && zones.length === 0;
  const zoneErrorMessage = axios.isAxiosError(zonesError)
    ? zonesError.response?.status === 401
      ? "Sign in with an operator account to load live zones."
      : "Backend API is offline. Start Docker Desktop and run docker compose up."
    : "No live zones returned from the backend.";

  // If no zone selected initially, select the first critical one
  useEffect(() => {
    if (!selectedZone && zones && zones.length > 0) {
      const criticalZone = zones.find(
        (z: any) => (z.priority_score || 0) > 70 || (z.victim_count || 0) > 0
      );
      if (criticalZone) {
        setSelectedZone(criticalZone.zone_id);
        navigate(`/dashboard/${criticalZone.zone_id}`, { replace: true });
      }
    }
  }, [zones, selectedZone, navigate]);

  const headerItems = alerts.map((alert, index) => (
    <div
      key={index}
      className={`alert alert-${alert.type} mb-2 px-3 py-2 rounded text-sm`}
    >
      {alert.message}
    </div>
  ));

  // Heatmap layer controls
  const heatmapLayers = [
    { key: "priority", label: "Priority Score", type: "priority" },
    { key: "victim-density", label: "Victim Density", type: "victim-density" },
    { key: "trust-score", label: "Trust Score", type: "trust-score" },
    { key: "combined", label: "Combined Metrics", type: "combined" },
  ];

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
            <button className="ops-button" onClick={() => setActiveHeatmap((h) => h === "combined" ? null : "combined")}>
              {activeHeatmap === "combined" ? "Hide heatmap" : "Heatmap"}
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
            <div><div className="ops-mono text-xs text-slate-300">SYSTEM MODE</div><div className="text-sm font-semibold">{isConnected ? "Live intelligence" : "Offline fallback"}</div></div>
          </div>
        </section>

        <section className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="ops-stat fade-in"><div className="ops-stat-label">Active incidents</div><div className="ops-stat-value">{selectedZone ? "03" : "07"}</div><div className="mt-2 text-xs text-[#ff6b6b]">↑ 2 need attention</div></div>
          <div className="ops-stat fade-in"><div className="ops-stat-label">People at risk</div><div className="ops-stat-value">1,284</div><div className="mt-2 text-xs text-[#f3b562]">37 detected in last hour</div></div>
          <div className="ops-stat fade-in"><div className="ops-stat-label">Response readiness</div><div className="ops-stat-value">82%</div><div className="ops-progress mt-2"><span style={{ width: "82%" }} /></div></div>
          <div className="ops-stat fade-in"><div className="ops-stat-label">Actions awaiting approval</div><div className="ops-stat-value text-[#f3b562]">04</div><div className="mt-2 text-xs text-slate-400">Commander review required</div></div>
        </section>

        <section className="ops-panel mb-6 flex flex-col gap-4 p-4 md:flex-row md:items-center md:justify-between">
          <div><div className="ops-kicker mb-1">Focus area</div><div className="text-sm text-slate-300">Choose an operational zone to filter every signal and recommendation.</div></div>
          <select aria-label="Select operational zone" value={selectedZone || ""} onChange={(e) => { const zoneId = e.target.value; setSelectedZone(zoneId || null); socketRef.current?.emit("subscribe", { room: zoneId ? `zone_${zoneId}` : "global_feed" }); navigate(`/dashboard/${zoneId || ""}`, { replace: true }); }} className="ops-select min-w-[250px]" disabled={loadingZones || zonesUnavailable}>
            <option value="">All operational zones</option>
            {zones.map((zone: any) => <option key={zone.zone_id} value={zone.zone_id}>{zone.name || `Zone ${zone.zone_id?.substring(0, 8)}`} {zone.priority_score ? `· ${zone.priority_score}/100` : ""}</option>)}
          </select>
          {zonesUnavailable && <div className="mt-2 text-xs text-[#f3b562]">{zoneErrorMessage}</div>}
        </section>

        {alerts.length > 0 && <div className="mb-5">{headerItems}</div>}

        <section className="grid grid-cols-1 gap-6 xl:grid-cols-[280px_minmax(0,1fr)_330px]">
          <div className="space-y-5">
            <LiveIncidentsPanel selectedZone={selectedZone} />
            <RecentReportsPanel selectedZone={selectedZone} />
            <ResourcePanel zoneId={selectedZone} />
          </div>

          <div className="space-y-5">
            <div className="ops-panel ops-glow overflow-hidden">
              <div className="ops-panel-header"><div><div className="ops-kicker">Operational map</div><div className="ops-title">Threat landscape</div></div><span className="ops-mono text-xs text-slate-400">{heatmapData ? "LIVE LAYER" : "SIMULATION"}</span></div>
              <OperationalMap zones={zones} selectedZone={selectedZone} onSelectZone={(zoneId) => { setSelectedZone(zoneId); navigate(`/dashboard/${zoneId}`, { replace: true }); }} />
            </div>
            {selectedZone ? <ZoneDetail zoneId={selectedZone} /> : <div className="ops-panel p-6"><div className="ops-kicker mb-2">No zone selected</div><div className="ops-title mb-2">Your next decision starts here.</div><p className="text-sm leading-6 text-slate-400">Select a zone above to open incident reasoning, victim detection, route intelligence, and response actions.</p></div>}
          </div>

          <div className="space-y-5">
            <div className="ops-panel p-5"><div className="ops-kicker mb-2">Decision queue</div><div className="ops-title mb-4">Human approval gate</div><div className="space-y-3">{["Dispatch Team Bravo to Zone A", "Release 70 medical kits", "Open Shelter C overflow"].map((item, index) => <button key={item} className="flex w-full items-center gap-3 rounded-lg border border-white/10 bg-white/[.03] p-3 text-left transition hover:border-[#38d9c4]/50"><span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold ${index === 0 ? "bg-[#ff6b6b]/20 text-[#ff8b8b]" : "bg-[#f3b562]/20 text-[#f3b562]"}`}>{index + 1}</span><span className="text-sm text-slate-200">{item}<small className="mt-1 block text-xs text-slate-500">AI confidence {96 - index * 7}% · pending</small></span></button>)}</div><button className="ops-button-primary mt-4 w-full rounded-lg" onClick={() => navigate("/command-center")}>Review queue</button></div>
            {selectedZone ? <CriticalZone3D zoneId={selectedZone} /> : <div className="ops-panel p-5"><div className="ops-kicker mb-2">3D zone view</div><div className="ops-title mb-2">Digital twin standby</div><p className="text-sm leading-6 text-slate-400">Select a critical zone to inspect terrain, structures, and rescue routes in 3D.</p></div>}
          </div>
        </section>
      </main>
    </div>
  );
};

/* Simple Components */

/* Badge for connection status */
const BadgeConnectionStatus: React.FC<{ isConnected: boolean }> = ({ isConnected }) => {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${isConnected ? "bg-green-500" : "bg-red-500"}`}
    >
      {isConnected ? "Online" : "Offline"}
    </span>
  );
};

/* Alerts Dropdown */
const AlertsDropdown: React.FC<{ alerts: { type: string; message: string }[] }> = ({
  alerts,
}) => {
  return (
    <div
      className="relative"
      onClick={() => alert("Alerts panel clicked")}
    >
      <svg
        className="w-5 h-5 text-yellow-300"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
        />
      </svg>
      <span className="hidden sm:block sm:ml-2">Alerts</span>
    </div>
  );
};