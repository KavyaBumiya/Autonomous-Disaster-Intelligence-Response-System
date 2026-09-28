import { useEffect, useMemo, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN } from "../lib/config";
import type { Incident, PredictionCell, Report, Resource, Zone } from "../lib/types";

interface MarkerData {
  x: number;
  y: number;
  c: string;
  label: string;
}

export interface MapVisibility {
  floodExtent: boolean;
  predictionCone: boolean;
  citizenReports: boolean;
  teamPositions: boolean;
  shelters: boolean;
  incidents: boolean;
}

interface LiveMapCanvasProps {
  mapLayer: string;
  markers?: MarkerData[];
  freshness?: string;
  /**
   * The selected operational zone. This is the single source of truth for the
   * map centre, so every call site must pass it; omitting it makes the map fall
   * back to a default that can contradict the selected zone shown elsewhere.
   */
  zone?: Zone | null;
  incidents?: Incident[] | null;
  reports?: Report[] | null;
  resources?: Resource[] | null;
  floodCells?: PredictionCell[] | null;
  visibility?: Partial<MapVisibility>;
}

/**
 * Last-resort centre used only when there is no selected zone and no mapped data
 * to derive one from. Deliberately not a real operational location: it is a
 * neutral Gujarat default so an empty map has somewhere to sit, and it is never
 * preferred over zone or data-derived coordinates.
 */
const FALLBACK_CENTER: [number, number] = [72.5714, 23.0225];

const DEFAULT_VISIBILITY: MapVisibility = {
  floodExtent: true,
  predictionCone: true,
  citizenReports: true,
  teamPositions: true,
  shelters: true,
  incidents: true,
};

function popupText(title: string, lines: string[]): string {
  return [title, ...lines.filter(Boolean)].join("\n");
}

function markerElement(color: string, size = 14): HTMLDivElement {
  const el = document.createElement("div");
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.style.borderRadius = "50%";
  el.style.background = color;
  el.style.border = "2px solid rgba(255,255,255,.9)";
  el.style.boxShadow = `0 0 12px ${color}`;
  return el;
}

function sourceFeatureCollection(points: Array<{ lng: number; lat: number; [key: string]: unknown }>) {
  return {
    type: "FeatureCollection" as const,
    features: points.map((point) => ({
      type: "Feature" as const,
      properties: Object.fromEntries(Object.entries(point).filter(([key]) => key !== "lng" && key !== "lat")),
      geometry: { type: "Point" as const, coordinates: [point.lng, point.lat] },
    })),
  };
}

export default function LiveMapCanvas({
  mapLayer,
  markers = [],
  freshness = "—",
  zone,
  incidents = [],
  reports = [],
  resources = [],
  floodCells = [],
  visibility,
}: LiveMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markerRefs = useRef<mapboxgl.Marker[]>([]);
  const vis = { ...DEFAULT_VISIBILITY, ...(visibility ?? {}) };

  // Type guards, not plain filters: the runtime check is what makes these points
  // safe to average, so the compiler has to see the narrowing too.
  const hasCoords = (p: { lat: number | null; lng: number | null }): p is { lat: number; lng: number } =>
    p.lat !== null && p.lng !== null;

  const teamPoints = useMemo(
    () => (resources ?? []).filter((r) => r.resource_type === "team").filter(hasCoords),
    [resources],
  );
  const shelterPoints = useMemo(
    () => (resources ?? []).filter((r) => r.resource_type === "shelter").filter(hasCoords),
    [resources],
  );
  const reportPoints = useMemo(() => (reports ?? []).filter(hasCoords), [reports]);
  const incidentPoints = useMemo(() => (incidents ?? []).filter(hasCoords), [incidents]);

  /**
   * Every mappable operational coordinate as a plain [lng, lat] list.
   *
   * Built here rather than by spreading the typed point arrays, because those
   * carry nullable lat/lng and the centre average needs definite numbers.
   */
  const allCoords = useMemo(() => {
    const out: Array<[number, number]> = [];
    for (const p of [...(resources ?? []), ...(reports ?? []), ...(incidents ?? [])]) {
      if (p.lat !== null && p.lat !== undefined && p.lng !== null && p.lng !== undefined) {
        out.push([p.lng, p.lat]);
      }
    }
    return out;
  }, [resources, reports, incidents]);

  /**
   * Resolve the map centre, in priority order:
   *   1. the selected zone centroid
   *   2. the centroid of whatever operational points are loaded
   *   3. a neutral fallback for a genuinely empty map
   *
   * Deriving from loaded data means a page that forgets to pass `zone` still
   * frames the incident it is actually showing, instead of parking the viewport
   * over an unrelated city. Held as primitives so the re-frame effect below
   * fires on a real coordinate change rather than on every poll tick.
   */
  const centerLng = useMemo(() => {
    if (zone) return zone.centroid_lng;
    if (allCoords.length === 0) return FALLBACK_CENTER[0];
    return allCoords.reduce((sum, c) => sum + c[0], 0) / allCoords.length;
  }, [zone?.centroid_lng, allCoords]);

  const centerLat = useMemo(() => {
    if (zone) return zone.centroid_lat;
    if (allCoords.length === 0) return FALLBACK_CENTER[1];
    return allCoords.reduce((sum, c) => sum + c[1], 0) / allCoords.length;
  }, [zone?.centroid_lat, allCoords]);

  useEffect(() => {
    if (!MAPBOX_TOKEN || !containerRef.current) return;

    mapboxgl.accessToken = MAPBOX_TOKEN;
    const initialCenter: [number, number] = [centerLng, centerLat];

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: initialCenter,
      zoom: zone ? 10 : 11,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "bottom-right");
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("flood-cells", {
        type: "geojson",
        data: sourceFeatureCollection([]),
      });
      map.addLayer({
        id: "flood-extent",
        type: "circle",
        source: "flood-cells",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "intensity"], 1, 5, 50, 10, 100, 18],
          "circle-color": "#ff5c69",
          "circle-opacity": 0.26,
          "circle-stroke-color": "#ff7b85",
          "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.5,
        },
      });
      map.addLayer({
        id: "prediction-cone",
        type: "circle",
        source: "flood-cells",
        paint: {
          "circle-radius": 24,
          "circle-color": "#ffbd5a",
          "circle-opacity": 0.035,
          "circle-stroke-color": "#ffbd5a",
          "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.2,
        },
      });

      const pointLayers = [
        ["citizen-reports", "#a78bfa"],
        ["incidents", "#ff5c69"],
        ["teams", "#35d39a"],
        ["shelters", "#39d9ff"],
      ] as const;
      for (const [id, color] of pointLayers) {
        map.addSource(id, { type: "geojson", data: sourceFeatureCollection([]) });
        map.addLayer({
          id: `${id}-layer`,
          type: "circle",
          source: id,
          paint: {
            "circle-radius": id === "incidents" ? 7 : 5,
            "circle-color": color,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.5,
            "circle-opacity": 0.92,
          },
        });
      }
    });

    return () => {
      markerRefs.current.forEach((m) => m.remove());
      markerRefs.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [zone?.zone_id]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const update = () => {
      const floodSource = map.getSource("flood-cells") as mapboxgl.GeoJSONSource | undefined;
      floodSource?.setData(sourceFeatureCollection(
        (floodCells ?? []).map((cell) => ({ lat: cell.lat, lng: cell.lng, intensity: cell.intensity, time_step: cell.time_step })),
      ));

      const reportSource = map.getSource("citizen-reports") as mapboxgl.GeoJSONSource | undefined;
      reportSource?.setData(sourceFeatureCollection(
        reportPoints.map((report) => ({ lat: report.lat as number, lng: report.lng as number, source: report.source, trust: report.trust_score ?? 0 })),
      ));

      const incidentSource = map.getSource("incidents") as mapboxgl.GeoJSONSource | undefined;
      incidentSource?.setData(sourceFeatureCollection(
        incidentPoints.map((incident) => ({ lat: incident.lat as number, lng: incident.lng as number, type: incident.disaster_type ?? "hazard", priority: incident.priority_score })),
      ));

      const teamSource = map.getSource("teams") as mapboxgl.GeoJSONSource | undefined;
      teamSource?.setData(sourceFeatureCollection(
        teamPoints.map((team) => ({ lat: team.lat as number, lng: team.lng as number, name: team.name })),
      ));

      const shelterSource = map.getSource("shelters") as mapboxgl.GeoJSONSource | undefined;
      shelterSource?.setData(sourceFeatureCollection(
        shelterPoints.map((shelter) => ({ lat: shelter.lat as number, lng: shelter.lng as number, name: shelter.name })),
      ));

      const setVisibility = (layerId: string, visible: boolean) => {
        if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      };
      setVisibility("flood-extent", vis.floodExtent);
      setVisibility("prediction-cone", vis.predictionCone);
      setVisibility("citizen-reports-layer", vis.citizenReports);
      setVisibility("incidents-layer", vis.incidents);
      setVisibility("teams-layer", vis.teamPositions);
      setVisibility("shelters-layer", vis.shelters);
    };

    if (map.isStyleLoaded()) update();
    else map.once("load", update);
  }, [floodCells, reportPoints, incidentPoints, teamPoints, shelterPoints, vis.floodExtent, vis.predictionCone, vis.citizenReports, vis.incidents, vis.teamPositions, vis.shelters]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    // Re-frame whenever the operational centre changes, whether that came from a
    // zone selection or from data arriving on a page that does not pass one.
    // This is what stops the viewport drifting away from the selected operation.
    map.easeTo({ center: [centerLng, centerLat], duration: 700 });
  }, [centerLng, centerLat]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRefs.current.forEach((m) => m.remove());
    markerRefs.current = [];
    // Legacy overview pins remain supported, but only as an overlay; all Live Map
    // operational layers above use real latitude/longitude backend data.
    markers.forEach((marker) => {
      const el = markerElement(marker.c);
      const popup = new mapboxgl.Popup({ offset: 18 }).setText(marker.label);
      // The legacy pins are authored in a synthetic 900x520 space. Anchor them to
      // whichever centre the map is actually using, so they stay with the
      // selected zone instead of being pinned to a hardcoded Ahmedabad offset.
      const [anchorLng, anchorLat] = [centerLng, centerLat];
      const lng = anchorLng + (marker.x - 450) * (0.45 / 900);
      const lat = anchorLat - (marker.y - 260) * (0.26 / 520);
      const m = new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).setPopup(popup).addTo(map);
      markerRefs.current.push(m);
    });
  }, [markers, centerLng, centerLat]);

  if (!MAPBOX_TOKEN) {
    return (
      <div className="flex h-[420px] items-center justify-center bg-[#091827] px-6 text-center text-sm text-slate-500">
        Mapbox is not configured. Add <code className="mx-1 text-cyan">VITE_MAPBOX_TOKEN</code> to the frontend deployment to enable the live map.
      </div>
    );
  }

  return (
    <div className="relative h-[420px]">
      <div ref={containerRef} className="h-full w-full" />
      <div className="absolute left-3 top-3 rounded-lg border border-line bg-[#07111f]/90 px-3 py-2 text-[10px] text-slate-400">
        {mapLayer} layer · Updated {freshness} · {incidentPoints.length} incidents · {teamPoints.length} teams
      </div>
    </div>
  );
}
