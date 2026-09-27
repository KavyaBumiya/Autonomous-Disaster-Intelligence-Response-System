import React, { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { io, type Socket } from "socket.io-client";

import { AppShell } from "@/components/AppShell";
import { KPIStrip } from "@/components/KPIStrip";
import { Button } from "@/components/ui";
import { WeatherWidget } from "@/components/WeatherWidget";
import { SeismicPanel } from "@/components/SeismicPanel";
import { LiveIncidentsPanel } from "./LiveIncidentsPanel";
import { RecentReportsPanel } from "./RecentReportsPanel";
import { ResourcePanel } from "./ResourceStatusPanel";
import { ZoneDetail } from "./ZoneDetail";

import {
  zonesApi,
  incidentsApi,
  resourcesApi,
  commandApi,
  heatmapsApi,
  type Zone,
  type Incident,
  type Resource,
} from "@/services/api";
import { useSystemHealthStore } from "@/stores/systemHealthStore";

const CesiumGlobe = lazy(() =>
  import("@/components/CesiumGlobe").then((m) => ({ default: m.CesiumGlobe }))
);

const MapFallback = ({ label }: { label: string }) => (
  <div className="ops-panel flex min-h-[320px] items-center justify-center p-6 text-center">
    <div>
      <div className="ops-kicker mb-2">{label}</div>
      <div className="ops-title">Loading 3D engine…</div>
      <p className="mt-2 text-sm text-slate-400">Cesium loads only when the globe is needed.</p>
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
  const socketRef = useRef<Socket | null>(null);

  const pushAlert = (type: string, message: string) => {
    setAlerts((prev) => [{ type, message }, ...prev].slice(0, 5));
  };

  // Connect to WebSocket on mount / zone change
  useEffect(() => {
    const socket = io(import.meta.env.VITE_WS_URL || "/", {
      transports: ["websocket", "polling"],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });
    socketRef.current = socket;

    socket.emit("subscribe", { room: "global_feed" });
    if (selectedZone) {
      socket.emit("subscribe", { room: `zone_${selectedZone}` });
    }

    socket.on("connect", () => {
      setIsConnected(true);
      useSystemHealthStore.getState().setRealtime("ONLINE");
      toast.success("Connected to AegisAI live feed");
    });

    socket.on("disconnect", () => {
      setIsConnected(false);
      useSystemHealthStore.getState().setRealtime("DEGRADED");
      toast.warning("Disconnected from live feed. Reconnecting...");
      setTimeout(() => socket.connect(), 5000);
    });

    socket.on("new_report", (data: { payload?: { disaster_type?: string; zone_id?: string } }) => {
      const msg = `New report: ${data.payload?.disaster_type || "unknown"} in zone ${data.payload?.zone_id}`;
      pushAlert("info", msg);
    });

    socket.on("trust_score_updated", (data: { payload?: { report_id?: string } }) => {
      pushAlert("warning", `Trust score updated for report ${data.payload?.report_id}`);
    });

    socket.on("incident_priority_updated", (data: { payload?: { incident_id?: string; new_priority?: number } }) => {
      pushAlert(
        "critical",
        `Priority updated for incident ${data.payload?.incident_id}: ${data.payload?.new_priority}`
      );
    });

    socket.on("new_incident", (data: { payload?: { disaster_type?: string; zone_id?: string } }) => {
      pushAlert(
        "critical",
        `New incident created: ${data.payload?.disaster_type} in zone ${data.payload?.zone_id}`
      );
      if (!selectedZone && data.payload?.zone_id) {
        navigate(`/dashboard/${data.payload.zone_id}`, { replace: true });
      }
    });

    socket.on("prediction_updated", (data: { payload?: { zone_id?: string } }) => {
      pushAlert("info", `Prediction updated for zone ${data.payload?.zone_id}`);
    });

    socket.on("resource_assigned", (data: { payload?: { action_id?: string } }) => {
      pushAlert("info", `Resource assigned to incident ${data.payload?.action_id}`);
    });

    socket.on("route_changed", (data: { payload?: { zone_id?: string } }) => {
      pushAlert("info", `Route changed for zone ${data.payload?.zone_id}`);
    });

    socket.on("command_interaction", (data: {
      payload?: { query?: string };
      event?: string;
    }) => {
      toast.info(`Command: ${data.payload?.query || data.event || "interaction"}`);
    });

    socket.on("action_state_changed", (data: {
      payload?: {
        action_id?: string;
        new_status?: string;
        changed_by_role?: string;
      };
    }) => {
      const p = data.payload || {};
      const statusLabels: Record<string, string> = {
        approved: "approved",
        rejected: "rejected",
        dispatched: "dispatched",
        completed: "completed",
      };
      const label = statusLabels[p.new_status || ""] || p.new_status;
      pushAlert(
        "info",
        `Action ${p.action_id}: ${label} by ${p.changed_by_role || "system"}`
      );
    });

    socket.on("resource_status_updated", (data: {
      payload?: {
        resource_id?: string;
        available?: boolean;
        current_load?: number;
        capacity?: number;
      };
      resource_id?: string;
      available?: boolean;
      current_load?: number;
      capacity?: number;
    }) => {
      const p = data.payload ?? data;
      const label = p.available ? "available" : "in use";
      pushAlert(
        "info",
        `Resource ${p.resource_id}: ${label} (load ${p.current_load}/${p.capacity})`
      );
    });

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
        const res = await heatmapsApi.combined(selectedZone);
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
  const {
    data: zoneResponse,
    isLoading: loadingZones,
    error: zonesError,
  } = useQuery<{
    zones: Zone[];
  }>({
    queryKey: ["zones"],
    queryFn: async () => {
      const res = await zonesApi.withPriority();
      return res.data;
    },
    refetchInterval: isConnected ? 15000 : 30000,
  });

  const zones = useMemo(() => zoneResponse?.zones ?? [], [zoneResponse]);
  const zonesUnavailable = !loadingZones && !zonesError && zones.length === 0;
  const apiBase = (import.meta.env.VITE_API_BASE_URL || "/").replace(/\/$/, "");
  const isVercelHost =
    typeof window !== "undefined" &&
    (Boolean(import.meta.env.VERCEL) || window.location.hostname.endsWith(".vercel.app"));
  const isLocalBackend =
    !isVercelHost &&
    (apiBase === "" ||
      apiBase === "/" ||
      apiBase.includes("localhost") ||
      apiBase.includes("127.0.0.1"));
  const zoneErrorMessage = axios.isAxiosError(zonesError)
    ? isLocalBackend
      ? "Backend API is offline. Start Docker Desktop and run docker compose up."
      : `Backend API is unreachable at ${apiBase || window.location.origin}. Check VITE_API_BASE_URL and that the API is running.`
    : zonesError
      ? "Could not reach the backend API. It may still be starting — retry shortly."
      : "No live zones returned from the backend.";

  type QueryLike<T> = {
    data?: T;
    isLoading: boolean;
    error: unknown;
  };

  function kpiDisplay<T>(
    q: QueryLike<T>,
    render: (data: T) => React.ReactNode,
  ): { value: React.ReactNode; detail?: React.ReactNode; tone?: KPIItemTone } {
    if (q.isLoading) {
      return { value: "…", detail: "Loading…", tone: "default" };
    }
    if (q.error) {
      return {
        value: "—",
        detail: "Unable to load — retry shortly",
        tone: "red",
      };
    }
    if (q.data === undefined) {
      return { value: "—", detail: "No response yet", tone: "default" };
    }
    return { value: render(q.data), tone: "default" };
  }

  type KPIItemTone = NonNullable<import("@/components/KPIStrip").KPIItem["tone"]>;

  // Live stats — derived from backend queries (not hardcoded)
  const incidentsQuery = useQuery<{ incidents: Incident[]; total: number }>({
    queryKey: ["incidents", "active"],
    queryFn: async () => {
      const res = await incidentsApi.list({ active_only: true, limit: 200 });
      return res.data;
    },
    refetchInterval: isConnected ? 15000 : 30000,
  });

  const resourcesQuery = useQuery<{ resources: Resource[]; total: number }>({
    queryKey: ["resources", "all"],
    queryFn: async () => {
      const res = await resourcesApi.list({});
      return res.data;
    },
    refetchInterval: isConnected ? 15000 : 30000,
  });

  const queueQuery = useQuery({
    queryKey: ["approval-queue"],
    queryFn: async () => {
      const res = await commandApi.approvalQueue();
      return res.data;
    },
    refetchInterval: 15000,
  });

  const resourcesData = resourcesQuery.data;
  const queueData = queueQuery.data;

  const resources = resourcesData?.resources ?? [];
  const availableResources = resources.filter(
    (r) => r.available && r.current_load < r.capacity,
  );
  const readiness =
    resources.length > 0
      ? Math.round((availableResources.length / resources.length) * 100)
      : 0;

  // Default to first critical zone when nothing selected (derived, not effect)
  const defaultZoneId = useMemo(() => {
    if (zones.length === 0) return null;
    const critical = zones.find(
      (z) => (z.priority_score || 0) > 70 || (z.victim_count || 0) > 0
    );
    return critical?.zone_id ?? zones[0]?.zone_id ?? null;
  }, [zones]);

  const activeZone = selectedZone ?? defaultZoneId;

  // Zone coordinates for the weather widget (Phase 15)
  const activeZoneObj = useMemo(
    () => zones.find((z) => z.zone_id === activeZone) ?? null,
    [zones, activeZone],
  );

  // Keep URL in sync when a default zone is chosen
  useEffect(() => {
    if (!selectedZone && defaultZoneId) {
      navigate(`/dashboard/${defaultZoneId}`, { replace: true });
    }
  }, [selectedZone, defaultZoneId, navigate]);

  const headerItems = alerts.map((alert, index) => (
    <div
      key={`${alert.type}-${index}`}
      className={`ops-alert ops-alert-${alert.type} mb-2`}
      role="status"
    >
      <span aria-hidden="true">
        {alert.type === "critical" ? "▲" : alert.type === "warning" ? "△" : "ℹ"}
      </span>
      <span>{alert.message}</span>
    </div>
  ));

  return (
    <AppShell isConnected={isConnected} alertCount={alerts.length}>
      <section className="fade-in mb-6 flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div>
          <div className="ops-kicker mb-2">Live operations picture</div>
          <h1 className="max-w-3xl text-3xl font-bold tracking-tight text-white md:text-4xl">
            See the threat. <span className="text-[#38d9c4]">Move first.</span>
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
            A decision surface for incident commanders. Every signal is ranked, explained, and ready for human approval.
          </p>
        </div>
        <div className="ops-panel flex items-center gap-3 px-4 py-3">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              isConnected
                ? "bg-[#38d9c4] shadow-[0_0_14px_#38d9c4]"
                : "bg-[#f3b562] shadow-[0_0_14px_#f3b562]"
            }`}
          />
          <div>
            <div className="ops-mono text-xs text-slate-300">SYSTEM MODE</div>
            <div className="text-sm font-semibold">
              {isConnected ? "Live intelligence" : "Offline fallback"}
            </div>
          </div>
        </div>
      </section>

      <KPIStrip
        items={[
          (() => {
            const k = kpiDisplay(incidentsQuery, (d) =>
              String(d.incidents.length).padStart(2, "0"),
            );
            return {
              label: "Active incidents",
              value: k.value,
              detail: incidentsQuery.data
                ? `${
                    incidentsQuery.data.incidents.filter((i) => (i.priority_score || 0) > 70)
                      .length
                  } need attention`
                : k.detail,
              tone: k.tone === "default" ? "red" : k.tone,
            };
          })(),
          (() => {
            const k = kpiDisplay(incidentsQuery, (d) =>
              d.incidents
                .reduce((sum, inc) => sum + (inc.victim_count || 0), 0)
                .toLocaleString(),
            );
            return {
              label: "People at risk",
              value: k.value,
              detail: incidentsQuery.data
                ? "Detected across active zones"
                : k.detail,
              tone: k.tone === "default" ? "amber" : k.tone,
            };
          })(),
          (() => {
            const k = kpiDisplay(resourcesQuery, (d) => {
              const list = d.resources ?? [];
              if (list.length === 0) return "—";
              const avail = list.filter(
                (r) => r.available && r.current_load < r.capacity,
              ).length;
              return `${Math.round((avail / list.length) * 100)}%`;
            });
            const showProgress =
              !resourcesQuery.isLoading && !resourcesQuery.error && resources.length > 0;
            return {
              label: "Response readiness",
              value: k.value,
              detail: k.detail,
              tone: (k.tone === "default" ? "cyan" : k.tone) as KPIItemTone,
              progress: showProgress ? readiness : undefined,
            };
          })(),
          (() => {
            const k = kpiDisplay(queueQuery, (d) =>
              String(d.pending_count ?? 0).padStart(2, "0"),
            );
            return {
              label: "Actions awaiting approval",
              value: k.value,
              detail: queueQuery.data
                ? queueQuery.data.pending_count === 0
                  ? "Queue is clear"
                  : "Commander review required"
                : k.detail,
              tone: (k.tone === "default" ? "amber" : k.tone) as KPIItemTone,
            };
          })(),
        ]}
      />

      <section className="ops-panel mb-6 flex flex-col gap-4 p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="ops-kicker mb-1">Focus area</div>
          <div className="text-sm text-slate-300">
            Choose an operational zone to filter every signal and recommendation.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
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
          <Button
            variant={effectiveActiveHeatmap === "combined" ? "primary" : "default"}
            onClick={() => setActiveHeatmap((h) => (h === "combined" ? null : "combined"))}
          >
            {effectiveActiveHeatmap === "combined" ? "Hide heatmap" : "Heatmap"}
          </Button>
          <Button onClick={() => navigate("/command")}>Command center</Button>
        </div>
        {zonesUnavailable && (
          <div className="text-xs text-[#f3b562] md:w-full">{zoneErrorMessage}</div>
        )}
      </section>

      {alerts.length > 0 && <div className="mb-5">{headerItems}</div>}

      <section className="ops-dashboard-grid">
        <div className="ops-dashboard-left space-y-5">
          <LiveIncidentsPanel selectedZone={activeZone} />
          <RecentReportsPanel selectedZone={activeZone} />
          <ResourcePanel zoneId={activeZone} compact />
        </div>

        <div className="ops-dashboard-main space-y-5">
          <div className="ops-panel ops-glow overflow-hidden">
            <div className="ops-panel-header">
              <div>
                <div className="ops-kicker">3D Globe</div>
                <div className="ops-title">Threat landscape</div>
              </div>
              <span className="ops-mono text-xs text-slate-400">
                {effectiveHeatmapData ? "LIVE LAYER" : "SIMULATION"}
              </span>
            </div>
            <Suspense fallback={<MapFallback label="3D Globe" />}>
              <CesiumGlobe
                zones={zones}
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
                Select a zone above to open incident reasoning, victim detection, route
                intelligence, and response actions.
              </p>
            </div>
          )}
        </div>

        <div className="ops-dashboard-right space-y-5">
          {activeZoneObj &&
            Number.isFinite(activeZoneObj.centroid_lat) &&
            Number.isFinite(activeZoneObj.centroid_lng) && (
              <WeatherWidget
                lat={activeZoneObj.centroid_lat}
                lng={activeZoneObj.centroid_lng}
                label={activeZoneObj.name || "Zone conditions"}
              />
            )}

          <SeismicPanel />

          <div className="ops-panel">
            <div className="ops-panel-header">
              <div>
                <div className="ops-kicker">Decision queue</div>
                <div className="ops-title">Human approval gate</div>
              </div>
            </div>
            <div className="ops-panel-body space-y-3">
              {queueQuery.isLoading ? (
                <p className="text-xs text-slate-500">Loading approval queue…</p>
              ) : queueQuery.error ? (
                <p className="text-xs text-[#ff6b6b]">Unable to load approval queue.</p>
              ) : (
                (queueData?.actions ?? []).slice(0, 3).map((action) => (
                  <button
                    key={action.action_id}
                    className="flex w-full items-center gap-3 rounded-lg border border-white/10 bg-white/[.03] p-3 text-left transition hover:border-[#38d9c4]/50"
                    onClick={() => navigate("/command")}
                  >
                    <span
                      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold ${
                        (action.priority_score || 0) > 70
                          ? "bg-[#ff6b6b]/20 text-[#ff8b8b]"
                          : "bg-[#f3b562]/20 text-[#f3b562]"
                      }`}
                    >
                      {action.priority_band?.charAt(0) || "!"}
                    </span>
                    <span className="min-w-0 flex-1 text-sm text-slate-200">
                      <span className="ops-clamp-2 block">
                        {action.description?.slice(0, 60) || action.action_type}
                      </span>
                      <small className="mt-1 block text-xs text-slate-500">
                        Priority {(action.priority_score || 0).toFixed(0)}/100 · pending
                      </small>
                    </span>
                  </button>
                ))
              )}
              {!queueQuery.isLoading &&
                !queueQuery.error &&
                (queueData?.actions ?? []).length === 0 && (
                  <p className="text-xs text-slate-500">No pending actions — queue is clear.</p>
                )}
              <Button variant="primary" block onClick={() => navigate("/command")}>
                Review queue
              </Button>
            </div>
          </div>

          <div className="ops-panel">
            <div className="ops-panel-header">
              <div>
                <div className="ops-kicker">3D zone view</div>
                <div className="ops-title">Digital twin</div>
              </div>
            </div>
            <div className="ops-panel-body">
              <p className="mb-3 text-sm leading-6 text-slate-400">
                {activeZone
                  ? "Inspect terrain, structures, and rescue routes in an immersive 3D twin."
                  : "Select a critical zone to inspect terrain, structures, and rescue routes in 3D."}
              </p>
              <Button
                variant="primary"
                block
                disabled={!activeZone}
                onClick={() => activeZone && navigate(`/3d/${activeZone}`)}
              >
                Open 3D view
              </Button>
            </div>
          </div>
        </div>
      </section>
    </AppShell>
  );
};
