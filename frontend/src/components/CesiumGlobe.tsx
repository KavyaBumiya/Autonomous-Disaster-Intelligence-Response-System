import React, { useEffect, useMemo, useRef, useState } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import {
  EMPTY_LAYERS,
  LAYER_ORDER,
  type GlobeZone,
  type LayerKey,
  type MapLayers,
} from "./mapLayers";

const ION_TOKEN = (import.meta.env.VITE_CESIUM_ION_TOKEN || "").trim();
if (ION_TOKEN) Cesium.Ion.defaultAccessToken = ION_TOKEN;

/** Token-free base imagery so the globe still renders without a valid ion token. */
function fallbackBaseLayer(): Cesium.ImageryLayer {
  return Cesium.ImageryLayer.fromProviderAsync(
    Promise.resolve(
      new Cesium.OpenStreetMapImageryProvider({
        credit: new Cesium.Credit(
          '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
        ),
      }),
    ),
  );
}

/**
 * ion assets (satellite imagery, world terrain) 401 on an expired/revoked
 * token. Cesium then tries to decode the JSON error body as an image and the
 * render loop dies, so the token is probed before any ion asset is used.
 */
async function ionTokenUsable(signal: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch("https://api.cesium.com/v1/me", {
      headers: { Authorization: `Bearer ${ION_TOKEN}` },
      signal,
    });
    return res.ok;
  } catch {
    return false;
  }
}



interface CesiumGlobeProps {
  /** @deprecated pass `layers.zones`; kept for the existing single-page call sites */
  zones?: GlobeZone[];
  layers?: Partial<MapLayers>;
  visible?: Partial<Record<LayerKey, boolean>>;
  onSelectZone?: (zoneId: string) => void;
  onSelectIncident?: (incidentId: string) => void;
  onSelectResource?: (resourceId: string) => void;
  /** Pick handler for the layers that have no dedicated callback above. */
  onSelectFeature?: (kind: LayerKey, id: string) => void;
  height?: string;
  /** "bounds" frames every loaded zone — used by the full-screen regional view */
  autoFit?: "first" | "bounds";
  /** Fly to this coordinate whenever the value changes */
  focus?: { lat: number; lng: number; height?: number } | null;
  /** Increment to re-run the auto-fit (used by the "reset view" control) */
  resetToken?: number;
  showControls?: boolean;
}

const DISASTER_COLORS: Record<string, string> = {
  flood: "#38bdf8",
  earthquake: "#f59e0b",
  fire: "#ef4444",
  wildfire: "#ef4444",
  landslide: "#a78bfa",
  storm: "#22d3ee",
  cyclone: "#22d3ee",
  tsunami: "#6366f1",
  drought: "#eab308",
};

function disasterColor(type?: string | null): Cesium.Color {
  if (type && DISASTER_COLORS[type.toLowerCase()]) {
    return Cesium.Color.fromCssColorString(DISASTER_COLORS[type.toLowerCase()])!;
  }
  return Cesium.Color.ORANGE;
}

function priorityColor(priority: number): Cesium.Color {
  if (priority >= 70) return Cesium.Color.RED;
  if (priority >= 40) return Cesium.Color.ORANGE;
  return Cesium.Color.CYAN;
}

/** Normalise an unknown-scale magnitude to 0..1 against the dataset maximum. */
function normalise(value: number, max: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  if (!Number.isFinite(max) || max <= 0) return 0;
  return Math.min(1, value / max);
}

/** Cool → hot ramp used for weather risk and victim density. */
function heatColor(ratio: number): Cesium.Color {
  const t = Math.max(0, Math.min(1, ratio));
  if (t < 0.34) return Cesium.Color.fromCssColorString("#22d3ee")!;
  if (t < 0.67) return Cesium.Color.fromCssColorString("#f59e0b")!;
  return Cesium.Color.fromCssColorString("#ef4444")!;
}

const OUTLINE = { outlineColor: Cesium.Color.WHITE, outlineWidth: 2 } as const;

const NO_DEPTH_TEST = Number.POSITIVE_INFINITY;

export const CesiumGlobe: React.FC<CesiumGlobeProps> = ({
  zones,
  layers,
  visible,
  onSelectZone,
  onSelectIncident,
  onSelectResource,
  onSelectFeature,
  height = "clamp(400px, 60vh, 700px)",
  autoFit = "first",
  focus = null,
  resetToken = 0,
  showControls = false,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const sourcesRef = useRef<Partial<Record<LayerKey, Cesium.CustomDataSource>>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const data = useMemo<MapLayers>(
    () => ({
      ...EMPTY_LAYERS,
      ...layers,
      zones: layers?.zones ?? zones ?? [],
    }),
    [layers, zones],
  );

  const zoneIndex = useMemo(() => {
    const map = new Map<string, GlobeZone>();
    data.zones.forEach((z) => map.set(z.zone_id, z));
    return map;
  }, [data.zones]);

  const zoneIdList = useMemo(
    () => JSON.stringify(data.zones.map((z) => z.zone_id).sort()),
    [data.zones],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || viewerRef.current) return;

    let disposed = false;
    const controller = new AbortController();
    let viewer: Cesium.Viewer | null = null;

    const init = async () => {
      try {
        viewer = new Cesium.Viewer(container, {
          baseLayer: fallbackBaseLayer(),
          terrainProvider: new Cesium.EllipsoidTerrainProvider(),
          baseLayerPicker: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          animation: false,
          timeline: false,
          fullscreenButton: false,
          selectionIndicator: false,
          infoBox: false,
        });
      } catch (err) {
        if (!disposed) {
          setError(err instanceof Error ? err.message : "Cesium init failed");
        }
        return;
      }

      const globe = viewer;
      // A single bad tile or an unreachable provider must not stop the render
      // loop; Cesium rethrows render errors by default.
      globe.scene.rethrowRenderErrors = false;
      globe.scene.renderError.addEventListener(
        (_scene: Cesium.Scene, err: unknown) => {
          const message = err instanceof Error ? err.message : String(err);
          console.warn("[CesiumGlobe] render error (non-fatal):", message);
        },
      );

      viewerRef.current = globe;
      if (disposed) {
        globe.destroy();
        return;
      }
      setReady(true);

      if (!ION_TOKEN) {
        setNotice(
          "No VITE_CESIUM_ION_TOKEN — showing OpenStreetMap imagery and ellipsoid terrain.",
        );
        return;
      }

      const usable = await ionTokenUsable(controller.signal);
      if (disposed || !viewerRef.current) return;

      if (!usable) {
        setNotice(
          "Cesium Ion token rejected (401) — showing OpenStreetMap imagery and ellipsoid terrain.",
        );
        return;
      }

      try {
        // ion asset 1 is TERRAIN (Cesium World Terrain); base imagery is
        // resolved by createWorldImageryAsync (Bing Maps Aerial, asset 2).
        globe.imageryLayers.addImageryProvider(
          await Cesium.createWorldImageryAsync(),
        );
        globe.terrainProvider = await Cesium.createWorldTerrainAsync({
          requestVertexNormals: true,
          requestWaterMask: true,
        });
      } catch (err) {
        console.warn(
          "[CesiumGlobe] ion upgrade failed:",
          err instanceof Error ? err.message : String(err),
        );
        setNotice("Cesium Ion assets unavailable — using OpenStreetMap base imagery.");
      }
    };

    void init();

    return () => {
      disposed = true;
      controller.abort();
      viewerRef.current = null;
      sourcesRef.current = {};
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;

    const replace = (key: LayerKey, build: (ds: Cesium.CustomDataSource) => void) => {
      const existing = sourcesRef.current[key];
      if (existing) {
        if (!viewer.isDestroyed()) viewer.dataSources.remove(existing, false);
        delete sourcesRef.current[key];
      }
      const ds = new Cesium.CustomDataSource(key);
      build(ds);
      viewer.dataSources.add(ds);
      sourcesRef.current[key] = ds;
    };

    replace("zones", (ds) => {
      data.zones.forEach((zone) => {
        if (!Number.isFinite(zone.centroid_lat) || !Number.isFinite(zone.centroid_lng)) return;
        const priority = zone.priority_score ?? 0;
        const color = priorityColor(priority);
        const radius = Math.max(200, zone.radius_meters ?? 800);

        ds.entities.add({
          id: `zone-${zone.zone_id}`,
          position: Cesium.Cartesian3.fromDegrees(zone.centroid_lng, zone.centroid_lat),
          point: {
            pixelSize: Math.max(8, Math.min(24, priority / 4 + 8)),
            color,
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          ellipse: {
            semiMajorAxis: radius,
            semiMinorAxis: radius,
            material: color.withAlpha(0.18),
            outline: true,
            outlineColor: color.withAlpha(0.85),
            height: 0,
          },
          label: {
            text: zone.name || "Zone",
            font: "12px sans-serif",
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 2,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -20),
            show: priority >= 40,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { kind: "zone", id: zone.zone_id },
        });
      });
    });

    replace("incidents", (ds) => {
      data.incidents.forEach((incident) => {
        const zone = incident.zone_id ? zoneIndex.get(incident.zone_id) : undefined;
        const lat = incident.lat ?? zone?.centroid_lat;
        const lng = incident.lng ?? zone?.centroid_lng;
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        const priority = incident.priority_score ?? 0;
        const color = disasterColor(incident.disaster_type);

        ds.entities.add({
          id: `incident-${incident.incident_id}`,
          position: Cesium.Cartesian3.fromDegrees(Number(lng), Number(lat)),
          point: {
            pixelSize: Math.max(10, Math.min(28, priority / 3 + 10)),
            color,
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: `${incident.disaster_type ?? "incident"} #${priority.toFixed(0)}`,
            font: "11px sans-serif",
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -24),
            show: priority >= 60,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { kind: "incident", id: incident.incident_id },
        });
      });
    });

    replace("resources", (ds) => {
      data.resources.forEach((resource) => {
        if (!Number.isFinite(resource.lat) || !Number.isFinite(resource.lng)) return;
        const free = resource.available !== false;
        const color = free ? Cesium.Color.LIME : Cesium.Color.GRAY;

        ds.entities.add({
          id: `resource-${resource.resource_id}`,
          position: Cesium.Cartesian3.fromDegrees(Number(resource.lng), Number(resource.lat)),
          point: {
            pixelSize: 9,
            color,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: resource.name ?? resource.resource_type ?? "Resource",
            font: "10px sans-serif",
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -14),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { kind: "resource", id: resource.resource_id },
        });
      });
    });

    replace("earthquakes", (ds) => {
      data.earthquakes.forEach((eq, idx) => {
        if (!Number.isFinite(eq.lat) || !Number.isFinite(eq.lng)) return;
        const mag = eq.magnitude ?? 0;
        ds.entities.add({
          id: `eq-${eq.usgs_id ?? eq.id ?? idx}`,
          position: Cesium.Cartesian3.fromDegrees(eq.lng, eq.lat),
          point: {
            pixelSize: Math.max(6, Math.min(22, mag * 3)),
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: `M${mag.toFixed(1)}`,
            font: "10px sans-serif",
            fillColor: Cesium.Color.YELLOW,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -12),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { kind: "earthquake", id: eq.usgs_id ?? eq.id ?? "" },
        });
      });
    });

    replace("fires", (ds) => {
      data.fires.forEach((fire, idx) => {
        if (!Number.isFinite(fire.latitude) || !Number.isFinite(fire.longitude)) return;
        const frp = fire.frp ?? 0;
        ds.entities.add({
          id: `fire-${idx}`,
          position: Cesium.Cartesian3.fromDegrees(fire.longitude, fire.latitude),
          point: {
            pixelSize: Math.max(4, Math.min(16, 4 + frp / 20)),
            color: Cesium.Color.fromCssColorString("#ff3b30")!,
            outlineColor: Cesium.Color.YELLOW,
            outlineWidth: 1,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { kind: "fire", id: String(idx) },
        });
      });
    });

    replace("reports", (ds) => {
      data.reports.forEach((report, idx) => {
        if (!Number.isFinite(report.lat) || !Number.isFinite(report.lng)) return;
        const trust = report.trust_score ?? 0.5;
        ds.entities.add({
          id: `report-${report.report_id ?? report.id ?? idx}`,
          position: Cesium.Cartesian3.fromDegrees(Number(report.lng), Number(report.lat)),
          point: {
            pixelSize: 5 + Math.round(trust * 5),
            color: Cesium.Color.fromCssColorString("#a78bfa")!.withAlpha(
              0.35 + trust * 0.65,
            ),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 1,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { kind: "report", id: report.report_id ?? report.id ?? "" },
        });
      });
    });

    // ── Model projection (GET /api/predictions/{zone_id}) ─────────────────
    // The engine emits grid POINTS, not polygons, so each cell is its own
    // intensity-scaled marker. Intensity is normalised against the run maximum
    // because the engine's scale is not guaranteed to be 0..1.
    replace("predictions", (ds) => {
      const maxIntensity = data.predictions.reduce(
        (max, cell) => Math.max(max, cell.intensity ?? 0),
        0,
      );
      data.predictions.forEach((cell, idx) => {
        if (!Number.isFinite(cell.lat) || !Number.isFinite(cell.lng)) return;
        const ratio = normalise(cell.intensity, maxIntensity);
        if (ratio <= 0) return;
        const base = disasterColor(cell.disaster_type);

        ds.entities.add({
          id: `prediction-${cell.zone_id}-${cell.disaster_type}-${idx}`,
          position: Cesium.Cartesian3.fromDegrees(cell.lng, cell.lat),
          point: {
            pixelSize: 5 + Math.round(ratio * 13),
            color: base.withAlpha(0.25 + ratio * 0.65),
            ...OUTLINE,
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          properties: {
            kind: "predictions",
            id: `${cell.zone_id}|${cell.disaster_type}`,
          },
        });
      });

      // One summary label per (zone, disaster) run, placed on its strongest cell.
      const strongest = new Map<string, { cell: (typeof data.predictions)[number]; ratio: number }>();
      data.predictions.forEach((cell) => {
        if (!Number.isFinite(cell.lat) || !Number.isFinite(cell.lng)) return;
        const key = `${cell.zone_id}|${cell.disaster_type}`;
        const ratio = normalise(cell.intensity, maxIntensity);
        const current = strongest.get(key);
        if (!current || ratio > current.ratio) strongest.set(key, { cell, ratio });
      });
      strongest.forEach(({ cell, ratio }) => {
        if (ratio <= 0) return;
        ds.entities.add({
          id: `prediction-label-${cell.zone_id}-${cell.disaster_type}`,
          position: Cesium.Cartesian3.fromDegrees(cell.lng, cell.lat),
          point: { pixelSize: 0, color: Cesium.Color.TRANSPARENT },
          label: {
            text: `${cell.disaster_type} ${(ratio * 100).toFixed(0)}%`,
            font: "10px sans-serif",
            fillColor: disasterColor(cell.disaster_type),
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -26),
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
        });
      });
    });

    // ── Victim density (GET /api/heatmaps/victim-density) ─────────────────
    replace("victims", (ds) => {
      const maxDensity = data.victims.reduce(
        (max, cell) => Math.max(max, cell.victim_density ?? 0),
        0,
      );
      data.victims.forEach((cell) => {
        if (!Number.isFinite(cell.lat) || !Number.isFinite(cell.lng)) return;
        const ratio = normalise(cell.victim_density, maxDensity);
        const color = heatColor(ratio);

        ds.entities.add({
          id: `victim-${cell.zone_id}`,
          position: Cesium.Cartesian3.fromDegrees(cell.lng, cell.lat),
          point: {
            pixelSize: 8 + Math.round(ratio * 14),
            color: color.withAlpha(0.85),
            ...OUTLINE,
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          ellipse: {
            semiMajorAxis: 600 + ratio * 5200,
            semiMinorAxis: 600 + ratio * 5200,
            material: color.withAlpha(0.14),
            outline: true,
            outlineColor: color.withAlpha(0.6),
            height: 0,
          },
          label: {
            text: `${cell.victim_count ?? 0}`,
            font: "10px sans-serif",
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -18),
            show: ratio > 0,
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          properties: { kind: "victims", id: cell.zone_id },
        });
      });
    });

    // ── Shelters (resource_type === "shelter") ───────────────────────────
    replace("shelters", (ds) => {
      data.shelters.forEach((shelter) => {
        if (!Number.isFinite(shelter.lat) || !Number.isFinite(shelter.lng)) return;
        const capacity = shelter.capacity ?? 0;
        const load = shelter.current_load ?? 0;
        const fill = capacity > 0 ? Math.min(1, load / capacity) : 1;
        // green → amber → red as the shelter fills; no capacity means "unknown"
        const color =
          capacity <= 0
            ? Cesium.Color.GRAY
            : fill >= 0.9
              ? Cesium.Color.RED
              : fill >= 0.6
                ? Cesium.Color.ORANGE
                : Cesium.Color.LIME;
        const free = Math.max(0, capacity - load);

        ds.entities.add({
          id: `shelter-${shelter.resource_id}`,
          position: Cesium.Cartesian3.fromDegrees(shelter.lng, shelter.lat),
          point: {
            pixelSize: 11,
            color,
            ...OUTLINE,
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          ellipse: {
            semiMajorAxis: 400,
            semiMinorAxis: 400,
            material: color.withAlpha(0.2),
            outline: true,
            outlineColor: color.withAlpha(0.8),
            height: 0,
          },
          label: {
            text:
              capacity > 0
                ? `${shelter.name ?? "Shelter"} ${free}/${capacity}`
                : (shelter.name ?? "Shelter"),
            font: "10px sans-serif",
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -16),
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          properties: { kind: "shelters", id: shelter.resource_id },
        });
      });
    });

    // ── Evacuation routes (POST /api/routes/compute) ─────────────────────
    // `geometry` is a plain [lng, lat] pair array, not GeoJSON.
    replace("routes", (ds) => {
      data.routes.forEach((route) => {
        const positions = (route.geometry ?? []).filter(
          (pair) =>
            Array.isArray(pair) &&
            pair.length >= 2 &&
            Number.isFinite(pair[0]) &&
            Number.isFinite(pair[1]),
        );
        if (positions.length < 2) return;

        const flat: number[] = [];
        positions.forEach(([lng, lat]) => {
          flat.push(lng, lat);
        });
        const color = disasterColor(route.disaster_type);

        ds.entities.add({
          id: `route-${route.zone_id}`,
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(flat),
            width: 4,
            material: new Cesium.PolylineGlowMaterialProperty({
              color: color.withAlpha(0.9),
              glowPower: 0.22,
            }),
          },
          properties: { kind: "routes", id: route.zone_id },
        });

        const [midLng, midLat] = positions[Math.floor(positions.length / 2)];
        ds.entities.add({
          id: `route-label-${route.zone_id}`,
          position: Cesium.Cartesian3.fromDegrees(midLng, midLat),
          point: { pixelSize: 0, color: Cesium.Color.TRANSPARENT },
          label: {
            text: `${route.distance_km.toFixed(1)}km · ${route.estimated_minutes}min`,
            font: "10px sans-serif",
            fillColor: color,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -16),
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
        });
      });
    });

    // ── Weather (GET /api/weather/current per zone centroid) ─────────────
    replace("weather", (ds) => {
      data.weather.forEach((wx, idx) => {
        if (!Number.isFinite(wx.lat) || !Number.isFinite(wx.lng)) return;
        // risk_score is a 0..1 risk, so it is already on-scale.
        const ratio = Math.max(0, Math.min(1, wx.risk_score ?? 0));
        const color = heatColor(ratio);

        ds.entities.add({
          id: `weather-${wx.zone_id ?? idx}`,
          position: Cesium.Cartesian3.fromDegrees(wx.lng, wx.lat),
          point: {
            pixelSize: 10,
            color: color.withAlpha(0.9),
            ...OUTLINE,
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          label: {
            text: `${wx.weather_main ?? "Wx"} ${ratio.toFixed(2)}`,
            font: "10px sans-serif",
            fillColor: color,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            verticalOrigin: Cesium.VerticalOrigin.TOP,
            pixelOffset: new Cesium.Cartesian2(0, 22),
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          properties: { kind: "weather", id: wx.zone_id ?? String(idx) },
        });
      });
    });

    // ── XAI: top contributing factor per incident ────────────────────────
    // Derived from `xai_reasoning` already present on the incidents payload.
    replace("xai", (ds) => {
      data.xai.forEach((entry) => {
        if (!Number.isFinite(entry.lat) || !Number.isFinite(entry.lng)) return;
        const color = priorityColor(entry.priority_score);

        ds.entities.add({
          id: `xai-${entry.incident_id}`,
          position: Cesium.Cartesian3.fromDegrees(entry.lng, entry.lat),
          point: {
            pixelSize: 7,
            color: color.withAlpha(0.95),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          label: {
            text: `${entry.top_factor} +${entry.top_factor_points.toFixed(1)}`,
            font: "10px monospace",
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Cesium.Color.BLACK,
            horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(16, 10),
            disableDepthTestDistance: NO_DEPTH_TEST,
          },
          properties: { kind: "xai", id: entry.incident_id },
        });
      });
    });
  }, [data, ready, zoneIndex]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    LAYER_ORDER.forEach((key) => {
      const ds = sourcesRef.current[key];
      if (ds) ds.show = visible?.[key] !== false;
    });
  }, [ready, visible]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready || zoneIdList === "[]") return;

    const valid = data.zones.filter(
      (z) => Number.isFinite(z.centroid_lat) && Number.isFinite(z.centroid_lng),
    );
    if (valid.length === 0) return;

    if (autoFit === "first") {
      const first = valid[0];
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(
          first.centroid_lng,
          first.centroid_lat,
          50000,
        ),
        duration: 1.5,
      });
      return;
    }

    const lats = valid.map((z) => z.centroid_lat);
    const lngs = valid.map((z) => z.centroid_lng);
    viewer.camera.flyTo({
      destination: Cesium.Rectangle.fromDegrees(
        Math.min(...lngs),
        Math.min(...lats),
        Math.max(...lngs),
        Math.max(...lats),
      ),
      duration: 1.5,
    });
    // zoneIdList is the identity of the loaded zone set; coordinates arrive with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoneIdList, ready, autoFit, resetToken]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready || !focus) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        focus.lng,
        focus.lat,
        focus.height ?? 25000,
      ),
      duration: 1.2,
    });
  }, [ready, focus]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    if (
      !onSelectZone &&
      !onSelectIncident &&
      !onSelectResource &&
      !onSelectFeature
    ) {
      return;
    }

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click: { position: Cesium.Cartesian2 }) => {
      const picked = viewer.scene.pick(click.position);
      if (!Cesium.defined(picked) || !picked.id) return;
      const props = picked.id.properties;
      if (!props) return;
      const kind = props.kind?.getValue();
      const id = props.id?.getValue();
      if (!kind || !id) return;
      if (kind === "zone") onSelectZone?.(id);
      if (kind === "incident") onSelectIncident?.(id);
      if (kind === "resource") onSelectResource?.(id);
      // Summary labels carry no pickable geometry of their own; their dummy
      // point is what gets picked, so route them to the same generic handler.
      if (kind && kind !== "zone" && kind !== "incident" && kind !== "resource") {
        onSelectFeature?.(kind as LayerKey, id);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => handler.destroy();
  }, [ready, onSelectZone, onSelectIncident, onSelectResource, onSelectFeature]);

  if (error) {
    return (
      <div
        className="flex items-center justify-center p-8 text-center text-sm text-slate-400"
        style={{ height }}
      >
        <div>
          <div className="mb-2 font-medium text-slate-300">3D Globe unavailable</div>
          <div className="max-w-md">{error}</div>
          <div className="mt-3 text-xs text-slate-500">
            The 3D globe needs a WebGL2-capable browser.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={containerRef} className="absolute inset-0" aria-label="3D disaster globe" />
      {!ready && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#0b1220]">
          <div className="text-sm text-slate-400">Loading 3D globe...</div>
        </div>
      )}
      {ready && notice && !showControls && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-slate-900/80 px-3 py-1.5 text-[11px] text-slate-300">
          {notice}
        </div>
      )}
    </div>
  );
};
