import React, { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { io, type Socket } from "socket.io-client";

import {
  zonesApi,
  incidentsApi,
  resourcesApi,
  reportsApi,
  earthquakesApi,
  firmsApi,
  predictionsApi,
  routesApi,
  weatherApi,
  heatmapsApi,
  type Zone,
  type Incident,
  type Resource,
  type Report,
  type EarthquakeEvent,
  type HeatmapResponse,
  type RoutesResult,
  type WeatherCurrent,
} from "@/services/api";
import { useSystemHealthStore } from "@/stores/systemHealthStore";
import { topXaiFactor } from "@/utils/xaiFactors";
import {
  LAYER_LABELS,
  LAYER_ORDER,
  PER_ZONE_LAYER_LIMIT,
  type GlobeFire,
  type GlobePredictionCell,
  type GlobeRoute,
  type GlobeShelter,
  type GlobeVictimCell,
  type GlobeWeather,
  type GlobeXaiFactor,
  type LayerKey,
  type MapLayers,
} from "@/components/mapLayers";

const CesiumGlobe = lazy(() =>
  import("@/components/CesiumGlobe").then((m) => ({ default: m.CesiumGlobe })),
);

const MAX_FIRE_POINTS = 1200;

const SECONDARY_LINKS = [
  { to: "/dashboard", label: "Dashboard", icon: "▦" },
  { to: "/command", label: "Command", icon: "◈" },
  { to: "/resources", label: "Resources", icon: "⬡" },
  { to: "/predictions", label: "Predictions", icon: "◎" },
  { to: "/heatmaps", label: "Heatmaps", icon: "◍" },
  { to: "/alerts", label: "Alerts", icon: "△" },
];

const MapFallback = () => (
  <div className="ops-panel flex h-full min-h-[320px] items-center justify-center p-6 text-center">
    <div>
      <div className="ops-kicker mb-2">3D engine</div>
      <div className="ops-title">Loading globe…</div>
      <p className="mt-2 text-sm text-slate-400">Cesium loads on first paint of the map.</p>
    </div>
  </div>
);

const LEGEND: Array<{ color: string; label: string }> = [
  { color: "#ff3b30", label: "Fire" },
  { color: "#38bdf8", label: "Flood" },
  { color: "#f59e0b", label: "Earthquake" },
  { color: "#22d3ee", label: "Storm" },
  { color: "#a78bfa", label: "Citizen report" },
  { color: "#84cc16", label: "Resource" },
  { color: "#ef4444", label: "High density" },
];

/** Fan-out helpers: one failed zone must not blank out the whole layer. */

function settled<T>(results: PromiseSettledResult<T>[]): T[] {
  return results
    .filter((r): r is PromiseFulfilledResult<T> => r.status === "fulfilled")
    .map((r) => r.value);
}

export const RegionalMapPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedFeature, setSelectedFeature] = useState<{
    kind: LayerKey;
    id: string;
  } | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [focus, setFocus] = useState<{ lat: number; lng: number; height?: number } | null>(null);
  const [resetToken, setResetToken] = useState(0);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>({
    zones: true,
    incidents: true,
    predictions: true,
    victims: true,
    resources: true,
    shelters: true,
    // One OSRM request per zone, so this starts switched off.
    routes: false,
    reports: true,
    earthquakes: true,
    fires: true,
    weather: true,
    xai: false,
  });
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    const socket = io(import.meta.env.VITE_WS_URL || "/", {
      transports: ["websocket", "polling"],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });
    socketRef.current = socket;
    socket.emit("subscribe", { room: "global_feed" });

    socket.on("connect", () => {
      setIsConnected(true);
      useSystemHealthStore.getState().setRealtime("ONLINE");
    });
    socket.on("disconnect", () => {
      setIsConnected(false);
      useSystemHealthStore.getState().setRealtime("DEGRADED");
    });
    ["new_incident", "prediction_updated", "new_report", "incident_priority_updated"].forEach(
      (evt) => {
        socket.on(evt, () => {
          void queryClient.invalidateQueries({ queryKey: ["incidents"] });
          void queryClient.invalidateQueries({ queryKey: ["zones"] });
          void queryClient.invalidateQueries({ queryKey: ["reports"] });
          void queryClient.invalidateQueries({ queryKey: ["predictions"] });
          void queryClient.invalidateQueries({ queryKey: ["victim-density"] });
        });
      },
    );

    return () => {
      socket.removeAllListeners();
      socket.disconnect();
      socketRef.current = null;
    };
  }, [queryClient]);

  const zonesQuery = useQuery<{ zones: Zone[] }>({
    queryKey: ["zones"],
    queryFn: async () => (await zonesApi.withPriority()).data,
    refetchInterval: isConnected ? 20000 : 45000,
  });

  const incidentsQuery = useQuery<{ incidents: Incident[] }>({
    queryKey: ["incidents", "map"],
    queryFn: async () =>
      (await incidentsApi.list({ active_only: true, limit: 300 })).data,
    refetchInterval: isConnected ? 15000 : 40000,
  });

  const resourcesQuery = useQuery<{ resources: Resource[] }>({
    queryKey: ["resources", "map"],
    queryFn: async () => (await resourcesApi.list({})).data,
    refetchInterval: isConnected ? 30000 : 60000,
  });

  const reportsQuery = useQuery<{ reports: Report[] }>({
    queryKey: ["reports", "map"],
    queryFn: async () => (await reportsApi.list({ limit: 200 })).data,
    refetchInterval: isConnected ? 30000 : 60000,
  });

  const earthquakesQuery = useQuery<{ earthquakes: EarthquakeEvent[] }>({
    queryKey: ["earthquakes", "map"],
    queryFn: async () =>
      (await earthquakesApi.recent({ minutes: 60 * 24 * 7, min_magnitude: 3, limit: 150 }))
        .data,
    refetchInterval: 300000,
  });

  const zones = useMemo(() => zonesQuery.data?.zones ?? [], [zonesQuery.data]);
  const incidents = useMemo(
    () => incidentsQuery.data?.incidents ?? [],
    [incidentsQuery.data],
  );
  const resources = useMemo(
    () => resourcesQuery.data?.resources ?? [],
    [resourcesQuery.data],
  );
  const reports = useMemo(() => reportsQuery.data?.reports ?? [], [reportsQuery.data]);
  const earthquakes = useMemo(
    () => earthquakesQuery.data?.earthquakes ?? [],
    [earthquakesQuery.data],
  );

  const regionCenter = useMemo(() => {
    const valid = zones.filter(
      (z) => Number.isFinite(z.centroid_lat) && Number.isFinite(z.centroid_lng),
    );
    if (valid.length === 0) return null;
    return {
      lat: valid.reduce((a, z) => a + z.centroid_lat, 0) / valid.length,
      lng: valid.reduce((a, z) => a + z.centroid_lng, 0) / valid.length,
    };
  }, [zones]);

  const firesQuery = useQuery<{ fires?: GlobeFire[] }>({
    queryKey: ["firms", "map", regionCenter?.lat, regionCenter?.lng],
    enabled: !!regionCenter && visible.fires,
    queryFn: async () => {
      if (!regionCenter) return { fires: [] };
      const res = await firmsApi.activeFires(
        regionCenter.lat,
        regionCenter.lng,
        1500,
        1,
      );
      const payload = res.data as { fires?: GlobeFire[] };
      return { fires: (payload.fires ?? []).slice(0, MAX_FIRE_POINTS) };
    },
    refetchInterval: 600000,
    retry: false,
  });

  // ── Model projection ───────────────────────────────────────────────────
  // One request per zone. The engine recomputes the 12h run on every call, so
  // the interval is deliberately coarse.
  const projectionZoneIds = useMemo(
    () => zones.slice(0, PER_ZONE_LAYER_LIMIT).map((z) => z.zone_id),
    [zones],
  );

  const predictionsQuery = useQuery<GlobePredictionCell[]>({
    queryKey: ["predictions", "map", projectionZoneIds],
    enabled: visible.predictions && projectionZoneIds.length > 0,
    queryFn: async () => {
      const results = await Promise.allSettled(
        projectionZoneIds.map((zoneId) => predictionsApi.forZone(zoneId)),
      );
      const cells: GlobePredictionCell[] = [];
      settled(results).forEach((res) => {
        const data = res.data;
        data.last_flood?.affected_cells?.forEach((cell) => {
          cells.push({
            zone_id: data.zone_id,
            disaster_type: "flood",
            lat: cell.lat,
            lng: cell.lng,
            intensity: cell.intensity,
            time_step: cell.time_step,
          });
        });
        data.last_fire?.burned_area?.forEach((cell) => {
          cells.push({
            zone_id: data.zone_id,
            disaster_type: "fire",
            lat: cell.lat,
            lng: cell.lng,
            intensity: cell.intensity,
            time_step: cell.time_step,
          });
        });
      });
      return cells;
    },
    refetchInterval: 300000,
    retry: false,
  });

  // ── Evacuation routes ──────────────────────────────────────────────────
  // The hazard type per zone is taken from its most frequent active incident
  // so the route avoids the road that actually matters.
  const routeTargets = useMemo(() => {
    const dominant = new Map<string, string>();
    incidents.forEach((incident) => {
      if (!incident.zone_id || !incident.disaster_type) return;
      dominant.set(incident.zone_id, incident.disaster_type);
    });
    return zones.slice(0, PER_ZONE_LAYER_LIMIT).map((z) => ({
      zone_id: z.zone_id,
      disaster_type: dominant.get(z.zone_id) ?? "flood",
    }));
  }, [zones, incidents]);

  const routesQuery = useQuery<GlobeRoute[]>({
    queryKey: ["routes", "map", routeTargets],
    enabled: visible.routes && routeTargets.length > 0,
    queryFn: async () => {
      const results = await Promise.allSettled(
        routeTargets.map((t) =>
          routesApi.compute({ zone_id: t.zone_id, disaster_type: t.disaster_type }),
        ),
      );
      const routes: GlobeRoute[] = [];
      settled(results).forEach((res) => {
        const data: RoutesResult = res.data;
        const geometry = (data.geometry ?? []).filter(
          (pair) =>
            Array.isArray(pair) &&
            pair.length >= 2 &&
            Number.isFinite(pair[0]) &&
            Number.isFinite(pair[1]),
        ) as [number, number][];
        if (geometry.length < 2) return;
        routes.push({
          zone_id: data.zone_id,
          zone_name: data.zone_name ?? null,
          disaster_type: data.disaster_type,
          geometry,
          distance_km: data.primary_route?.distance_km ?? 0,
          estimated_minutes: data.primary_route?.estimated_minutes ?? 0,
          source: data.source ?? null,
          engine: data.engine ?? null,
          blocked_roads: data.blocked_roads ?? [],
        });
      });
      return routes;
    },
    refetchInterval: 300000,
    retry: false,
  });

  // ── Weather ────────────────────────────────────────────────────────────
  const weatherQuery = useQuery<GlobeWeather[]>({
    queryKey: ["weather", "map", projectionZoneIds],
    enabled: visible.weather && projectionZoneIds.length > 0,
    queryFn: async () => {
      const targets = zones.slice(0, PER_ZONE_LAYER_LIMIT);
      // Tag each promise with its zone so a rejected sibling cannot shift the
      // index and misattribute a reading to the wrong zone.
      const results = await Promise.allSettled(
        targets.map((z) =>
          weatherApi
            .current(z.centroid_lat, z.centroid_lng)
            .then((res) => ({ zoneId: z.zone_id, res })),
        ),
      );
      const readings: GlobeWeather[] = [];
      results.forEach((outcome) => {
        if (outcome.status !== "fulfilled") return;
        const { zoneId, res } = outcome.value;
        const data: WeatherCurrent = res.data;
        if (!Number.isFinite(data.lat) || !Number.isFinite(data.lng)) return;
        readings.push({
          lat: data.lat,
          lng: data.lng,
          zone_id: zoneId,
          risk_score: data.risk_score ?? 0,
          rainfall_mm_hr: data.rainfall_mm_hr ?? 0,
          wind_speed_kmh: data.wind_speed_kmh ?? 0,
          temperature_c: data.temperature_c,
          weather_main: data.weather_main,
          provider: data.provider,
          from_cache: data.from_cache,
        });
      });
      return readings;
    },
    refetchInterval: 300000,
    retry: false,
  });

  // ── Victim density ─────────────────────────────────────────────────────
  const victimDensityQuery = useQuery<GlobeVictimCell[]>({
    queryKey: ["victim-density", "map"],
    enabled: visible.victims,
    queryFn: async () => {
      const res = await heatmapsApi.victimDensity();
      const data: HeatmapResponse = res.data;
      return (data.cells ?? [])
        .filter((c) => Number.isFinite(c.centroid_lat) && Number.isFinite(c.centroid_lng))
        .map((c) => ({
          zone_id: c.zone_id,
          zone_name: c.zone_name,
          lat: c.centroid_lat,
          lng: c.centroid_lng,
          victim_count: c.victim_count ?? 0,
          victim_density: c.victim_density ?? 0,
          area_km2: c.area_km2,
        }));
    },
    refetchInterval: 120000,
    retry: false,
  });

  const shelters = useMemo<GlobeShelter[]>(
    () =>
      resources
        .filter((r) => r.resource_type === "shelter")
        .filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lng))
        .map((r) => ({
          resource_id: r.resource_id,
          name: r.name,
          lat: Number(r.lat),
          lng: Number(r.lng),
          capacity: r.capacity ?? 0,
          current_load: r.current_load ?? 0,
          available: r.available !== false,
        })),
    [resources],
  );

  /**
   * XAI overlay, derived from `xai_reasoning` on the incidents already in
   * memory. This deliberately avoids GET /api/command/explain per incident,
   * which would fire one LLM narrative call for every marker on the map.
   */
  const xaiFactors = useMemo<GlobeXaiFactor[]>(
    () =>
      incidents.flatMap((incident) => {
        const zone = zones.find((z) => z.zone_id === incident.zone_id);
        const lat = incident.lat ?? zone?.centroid_lat;
        const lng = incident.lng ?? zone?.centroid_lng;
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return [];
        const top = topXaiFactor(incident.xai_reasoning);
        if (!top) return [];
        return [
          {
            incident_id: incident.incident_id,
            lat: Number(lat),
            lng: Number(lng),
            priority_score: incident.priority_score ?? 0,
            priority_band: incident.priority_band,
            top_factor: top.name,
            top_factor_points: top.points,
            top_factor_weight_pct: top.weightPct,
          },
        ];
      }),
    [incidents, zones],
  );

  const layers = useMemo<MapLayers>(
    () => ({
      zones: zones.map((z) => ({
        zone_id: z.zone_id,
        name: z.name,
        centroid_lat: z.centroid_lat,
        centroid_lng: z.centroid_lng,
        radius_meters: z.radius_meters,
        priority_score: z.priority_score,
        victim_count: z.victim_count,
      })),
      incidents: incidents.map((i) => ({
        incident_id: i.incident_id,
        zone_id: i.zone_id,
        disaster_type: i.disaster_type,
        lat: i.lat,
        lng: i.lng,
        priority_score: i.priority_score,
        severity_score: i.severity_score,
        status: i.status,
      })),
      predictions: predictionsQuery.data ?? [],
      victims: victimDensityQuery.data ?? [],
      resources: resources.map((r) => ({
        resource_id: r.resource_id,
        name: r.name,
        resource_type: r.resource_type,
        lat: r.lat,
        lng: r.lng,
        available: r.available,
        current_load: r.current_load,
        capacity: r.capacity,
      })),
      shelters,
      routes: routesQuery.data ?? [],
      earthquakes: earthquakes.map((e) => ({
        id: e.id,
        usgs_id: e.usgs_id,
        magnitude: e.magnitude,
        lat: e.lat,
        lng: e.lng,
        depth_km: e.depth_km,
        risk_score: e.risk_score,
      })),
      fires: firesQuery.data?.fires ?? [],
      weather: weatherQuery.data ?? [],
      xai: xaiFactors,
      reports: reports.map((r) => ({
        report_id: r.report_id ?? r.id,
        lat: r.lat,
        lng: r.lng,
        disaster_type: r.disaster_type,
        trust_score: r.trust_score,
      })),
    }),
    [
      zones,
      incidents,
      resources,
      reports,
      earthquakes,
      shelters,
      xaiFactors,
      predictionsQuery.data,
      victimDensityQuery.data,
      routesQuery.data,
      weatherQuery.data,
      firesQuery.data,
    ],
  );

  const counts = useMemo<Record<LayerKey, number>>(
    () => ({
      zones: layers.zones.length,
      incidents: layers.incidents.length,
      predictions: layers.predictions.length,
      victims: layers.victims.length,
      resources: layers.resources.length,
      shelters: layers.shelters.length,
      routes: layers.routes.length,
      reports: layers.reports.length,
      earthquakes: layers.earthquakes.length,
      fires: layers.fires.length,
      weather: layers.weather.length,
      xai: layers.xai.length,
    }),
    [layers],
  );

  const selectedIncident = useMemo(
    () => incidents.find((i) => i.incident_id === selectedIncidentId) ?? null,
    [incidents, selectedIncidentId],
  );

  const incidentXai = useMemo(
    () => topXaiFactor(selectedIncident?.xai_reasoning),
    [selectedIncident],
  );

  /** Detail rows for whichever non-incident layer entity was last picked. */
  const featureRows = useMemo<Array<[string, string]>>(() => {
    if (!selectedFeature) return [];
    const { kind, id } = selectedFeature;

    if (kind === "predictions") {
      const cells = layers.predictions.filter((c) => `${c.zone_id}|${c.disaster_type}` === id);
      if (cells.length === 0) return [];
      const peak = cells.reduce((a, b) => (b.intensity > a.intensity ? b : a));
      return [
        ["Run", id.replace("|", " / ")],
        ["Cells", String(cells.length)],
        ["Peak intensity", peak.intensity.toFixed(3)],
        ["Peak time step", String(peak.time_step)],
      ];
    }

    if (kind === "victims") {
      const cell = layers.victims.find((c) => c.zone_id === id);
      if (!cell) return [];
      return [
        ["Zone", cell.zone_name ?? cell.zone_id],
        ["Incidents w/ victims", String(cell.victim_count)],
        ["Victim density", (cell.victim_density ?? 0).toFixed(3)],
        ...(cell.area_km2 != null ? ([["Area", `${cell.area_km2.toFixed(1)} km²`]] as Array<[string, string]>) : []),
      ];
    }

    if (kind === "shelters") {
      const shelter = layers.shelters.find((s) => s.resource_id === id);
      if (!shelter) return [];
      const capacity = shelter.capacity ?? 0;
      const load = shelter.current_load ?? 0;
      return [
        ["Shelter", shelter.name ?? id],
        ["Capacity", String(capacity)],
        ["Occupied", String(load)],
        ["Free", String(Math.max(0, capacity - load))],
      ];
    }

    if (kind === "routes") {
      const route = layers.routes.find((r) => r.zone_id === id);
      if (!route) return [];
      return [
        ["Zone", route.zone_name ?? route.zone_id],
        ["Hazard", route.disaster_type],
        ["Distance", `${route.distance_km.toFixed(1)} km`],
        ["ETA", `${route.estimated_minutes} min`],
        ["Planner", route.source ?? route.engine ?? "unknown"],
        ["Blocked roads", route.blocked_roads.length ? route.blocked_roads.join(", ") : "none"],
      ];
    }

    if (kind === "weather") {
      const wx = layers.weather.find((w) => (w.zone_id ?? "") === id) ?? layers.weather[0];
      if (!wx) return [];
      return [
        ["Conditions", wx.weather_main],
        ["Risk score", wx.risk_score.toFixed(3)],
        ["Rainfall", `${wx.rainfall_mm_hr} mm/hr`],
        ["Wind", `${wx.wind_speed_kmh} km/h`],
        [
          "Temperature",
          wx.temperature_c == null ? "n/a" : `${wx.temperature_c.toFixed(1)} °C`,
        ],
        ["Provider", `${wx.provider}${wx.from_cache ? " (cached)" : ""}`],
      ];
    }

    if (kind === "xai") {
      const entry = layers.xai.find((x) => x.incident_id === id);
      if (!entry) return [];
      return [
        ["Incident", entry.incident_id],
        ["Top factor", entry.top_factor],
        ["Contribution", `+${entry.top_factor_points.toFixed(1)} pts`],
        ["PRD weight", `${entry.top_factor_weight_pct}%`],
        ["Priority", `${entry.priority_score.toFixed(0)} (${entry.priority_band ?? "—"})`],
      ];
    }

    return [];
  }, [selectedFeature, layers]);

  const kpis = useMemo(() => {
    const critical = incidents.filter((i) => (i.priority_score ?? 0) >= 70).length;
    const victims = zones.reduce((a, z) => a + (z.victim_count ?? 0), 0);
    const available = resources.filter(
      (r) => r.available && (r.current_load ?? 0) < (r.capacity ?? 0),
    ).length;
    return { critical, victims, available, total: resources.length };
  }, [incidents, zones, resources]);

  const backendDown = zonesQuery.isError;
  const anyLoading =
    zonesQuery.isLoading || incidentsQuery.isLoading || resourcesQuery.isLoading;

  return (
    <div className="relative h-screen w-full overflow-hidden bg-[#07101c]">
      <Suspense fallback={<MapFallback />}>
        <CesiumGlobe
          height="100%"
          layers={layers}
          visible={visible}
          autoFit="bounds"
          focus={focus}
          resetToken={resetToken}
          onSelectZone={(id) => setSelectedZoneId(id)}
          onSelectIncident={(id) => setSelectedIncidentId(id)}
          onSelectFeature={(kind, id) => {
            setSelectedFeature({ kind, id });
            setSelectedIncidentId(null);
          }}
        />
      </Suspense>

      {/* Top bar: identity, live status, links to the other pages */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-4 p-4">
        <div className="pointer-events-auto flex items-center gap-3 rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.82)] px-3 py-2 backdrop-blur">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[#38d9c4] text-sm font-bold text-[#07101c]">
            A
          </span>
          <div className="leading-tight">
            <div className="text-sm font-bold text-white">
              AegisAI <span className="font-normal text-slate-400">/ map</span>
            </div>
            <div className="ops-kicker text-[9px]">Regional operations picture</div>
          </div>
          <span
            className={`ops-badge ${
              isConnected ? "ops-badge-cyan" : "ops-badge-slate"
            }`}
          >
            <span className="ops-badge-dot" />
            {isConnected ? "Live" : "Offline"}
          </span>
        </div>

        <nav
          className="pointer-events-auto flex flex-wrap items-center justify-end gap-1 rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.82)] p-1 backdrop-blur"
          aria-label="Secondary pages"
        >
          {SECONDARY_LINKS.map((l) => (
            <button
              key={l.to}
              type="button"
              onClick={() => navigate(l.to)}
              className="ops-nav-link border-0 bg-transparent"
            >
              <span aria-hidden="true">{l.icon}</span>
              <span className="hidden sm:inline">{l.label}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* Left: KPIs + layer toggles */}
      <div className="pointer-events-none absolute bottom-4 left-4 top-20 z-20 flex w-[248px] flex-col gap-3">
        <div className="pointer-events-auto rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.82)] p-3 backdrop-blur">
          <div className="ops-kicker mb-2 text-[9px]">Live posture</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="ops-stat-value text-xl">
                {anyLoading ? "…" : kpis.critical}
              </div>
              <div className="ops-stat-label text-[10px]">Critical</div>
            </div>
            <div>
              <div className="ops-stat-value text-xl">
                {anyLoading ? "…" : kpis.victims}
              </div>
              <div className="ops-stat-label text-[10px]">Victims</div>
            </div>
            <div>
              <div className="ops-stat-value text-xl">
                {anyLoading ? "…" : `${kpis.available}/${kpis.total}`}
              </div>
              <div className="ops-stat-label text-[10px]">Resources</div>
            </div>
            <div>
              <div className="ops-stat-value text-xl">
                {zonesQuery.isLoading ? "…" : zones.length}
              </div>
              <div className="ops-stat-label text-[10px]">Zones</div>
            </div>
          </div>
        </div>

        <div className="pointer-events-auto overflow-y-auto rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.82)] p-3 backdrop-blur">
          <div className="ops-kicker mb-2 text-[9px]">Layers</div>
          <ul className="space-y-1">
            {LAYER_ORDER.map((key) => (
              <li key={key}>
                <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-xs text-slate-300 hover:bg-white/5">
                  <input
                    type="checkbox"
                    checked={visible[key]}
                    onChange={(e) =>
                      setVisible((prev) => ({ ...prev, [key]: e.target.checked }))
                    }
                    className="accent-[#38d9c4]"
                  />
                  <span className="flex-1">{LAYER_LABELS[key]}</span>
                  <span className="ops-mono text-[10px] text-slate-500">
                    {counts[key]}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="ops-button ops-button-sm mt-2 w-full"
            onClick={() => {
              setFocus(null);
              setResetToken((n) => n + 1);
            }}
          >
            Reset view
          </button>
        </div>
      </div>

      {/* Right: selected entity */}
      {selectedIncident && (
        <div className="absolute right-4 top-20 z-20 w-[300px] rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.9)] p-4 backdrop-blur">
          <div className="ops-kicker mb-1 text-[9px]">Incident</div>
          <div className="ops-title-sm mb-2">
            {selectedIncident.disaster_type ?? "Unknown"} ·{" "}
            {selectedIncident.incident_id}
          </div>
          <div className="space-y-1.5 text-xs text-slate-400">
            <div>Status: {selectedIncident.status}</div>
            <div>Priority: {Math.round(selectedIncident.priority_score ?? 0)}</div>
            <div>Severity: {Math.round(selectedIncident.severity_score ?? 0)}</div>
            <div>Reports: {selectedIncident.report_count}</div>
            <div>Victims: {selectedIncident.victim_count}</div>
            {incidentXai && (
              <div className="border-t border-white/10 pt-1.5">
                <div className="ops-kicker text-[9px]">Top XAI factor</div>
                <div className="ops-mono text-[11px] text-slate-300">
                  {incidentXai.name} +{incidentXai.points.toFixed(1)} pts
                  <span className="text-slate-500"> ({incidentXai.weightPct}%)</span>
                </div>
              </div>
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="ops-button ops-button-primary ops-button-sm flex-1"
              onClick={() => navigate(`/incidents/${selectedIncident.incident_id}`)}
            >
              Open incident
            </button>
            <button
              type="button"
              className="ops-button ops-button-sm"
              onClick={() => setSelectedIncidentId(null)}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Right: whichever prediction/victim/shelter/route/weather/xai entity
          was picked, falling through to the incident panel otherwise. */}
      {selectedFeature && featureRows.length > 0 && (
        <div className="absolute right-4 top-20 z-20 w-[300px] rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.9)] p-4 backdrop-blur">
          <div className="ops-kicker mb-1 text-[9px]">
            {LAYER_LABELS[selectedFeature.kind]}
          </div>
          <div className="ops-title-sm mb-2">{selectedFeature.id}</div>
          <dl className="space-y-1.5 text-xs">
            {featureRows.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3">
                <dt className="text-slate-500">{label}</dt>
                <dd className="ops-mono text-right text-slate-300">{value}</dd>
              </div>
            ))}
          </dl>
          {selectedFeature.kind === "xai" && (
            <button
              type="button"
              className="ops-button ops-button-primary ops-button-sm mt-3 w-full"
              onClick={() => navigate(`/incidents/${selectedFeature.id}`)}
            >
              Open incident
            </button>
          )}
          <button
            type="button"
            className="ops-button ops-button-sm mt-2 w-full"
            onClick={() => setSelectedFeature(null)}
          >
            Close
          </button>
        </div>
      )}

      {/* Bottom: legend + hints */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex items-end justify-between gap-4 p-4">
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.82)] px-3 py-2 backdrop-blur">
          {LEGEND.map((l) => (
            <span
              key={l.label}
              className="flex items-center gap-1.5 text-[10px] text-slate-300"
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: l.color }}
                aria-hidden="true"
              />
              {l.label}
            </span>
          ))}
        </div>
        {selectedZoneId && (
          <div className="pointer-events-auto rounded-xl border border-[var(--line)] bg-[rgba(7,16,28,.82)] px-3 py-2 backdrop-blur">
            <span className="text-[10px] text-slate-300">
              Zone <span className="ops-mono">{selectedZoneId}</span> selected
            </span>
          </div>
        )}
      </div>

      {backendDown && (
        <div className="pointer-events-none absolute inset-x-0 top-[86px] z-20 flex justify-center px-4">
          <div className="ops-alert ops-alert-warning max-w-xl">
            <span aria-hidden="true">△</span>
            <span>
              Backend API unreachable — the globe still renders, but live incident,
              resource and report layers are empty. Start the backend and retry.
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
