import React, { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useQuery } from "@tanstack/react-query";
import {
  incidentsApi,
  resourcesApi,
  heatmapsApi,
  type Zone,
} from "@/services/api";
import { useSystemHealthStore } from "@/stores/systemHealthStore";
import { useRouteStore } from "@/stores/routeStore";

interface OperationalMapProps {
  zones: Zone[];
  selectedZone: string | null;
  onSelectZone: (zoneId: string) => void;
  /** Optional CSS height override (e.g. compact panel map). */
  height?: string;
}

const DEFAULT_CENTER: [number, number] = [73.1812, 22.3072];

type LayerKey = "incidents" | "resources" | "heatmap" | "route";

const LAYER_IDS: Record<LayerKey, string> = {
  incidents: "aegis-incidents",
  resources: "aegis-resources",
  heatmap: "aegis-heatmap",
  route: "aegis-route",
};

const LAYER_LABELS: Record<LayerKey, string> = {
  incidents: "Incidents",
  resources: "Resources",
  heatmap: "Priority heatmap",
  route: "Computed route",
};

const EMPTY_GEOJSON: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

function hasUsableMapboxToken(): boolean {
  const token = import.meta.env.VITE_MAPBOX_TOKEN;
  return Boolean(
    token &&
      token !== "your_mapbox_access_token_here" &&
      token.startsWith("pk."),
  );
}

function addDataLayers(map: mapboxgl.Map): void {
  // Incidents — priority-colored circles
  map.addSource(LAYER_IDS.incidents, { type: "geojson", data: EMPTY_GEOJSON });
  map.addLayer({
    id: LAYER_IDS.incidents,
    type: "circle",
    source: LAYER_IDS.incidents,
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["get", "priority"],
        0, 5,
        100, 14,
      ],
      "circle-color": [
        "step",
        ["get", "priority"],
        "#38d9c4",
        40, "#f3b562",
        70, "#ff6b6b",
      ],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    },
  });

  // Resources — available (cyan) vs deployed/offline (slate)
  map.addSource(LAYER_IDS.resources, { type: "geojson", data: EMPTY_GEOJSON });
  map.addLayer({
    id: LAYER_IDS.resources,
    type: "circle",
    source: LAYER_IDS.resources,
    paint: {
      "circle-radius": 6,
      "circle-color": [
        "case",
        ["==", ["get", "available"], 1],
        "#38d9c4",
        "#64748b",
      ],
      "circle-stroke-color": "#0b1220",
      "circle-stroke-width": 1.5,
    },
  });

  // Priority heatmap at zone centroids
  map.addSource(LAYER_IDS.heatmap, { type: "geojson", data: EMPTY_GEOJSON });
  map.addLayer({
    id: LAYER_IDS.heatmap,
    type: "heatmap",
    source: LAYER_IDS.heatmap,
    maxzoom: 14,
    paint: {
      "heatmap-weight": ["interpolate", ["linear"], ["get", "weight"], 0, 0, 100, 1],
      "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 8, 0.7, 13, 2],
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 8, 25, 13, 70],
      "heatmap-opacity": 0.7,
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0, "rgba(11,18,32,0)",
        0.2, "#38d9c4",
        0.5, "#f3b562",
        1, "#ff6b6b",
      ],
    },
  });

  // Computed route line
  map.addSource(LAYER_IDS.route, { type: "geojson", data: EMPTY_GEOJSON });
  map.addLayer({
    id: LAYER_IDS.route,
    type: "line",
    source: LAYER_IDS.route,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": "#38d9c4",
      "line-width": 4,
      "line-opacity": 0.9,
    },
  });
}

export const OperationalMap: React.FC<OperationalMapProps> = ({
  zones,
  selectedZone,
  onSelectZone,
  height,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<mapboxgl.Marker[]>([]);
  const layersAddedRef = useRef(false);
  const hasToken = hasUsableMapboxToken();
  const mapHeight = height || "clamp(340px, 52vh, 640px)";

  const [mapReady, setMapReady] = useState(false);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>({
    incidents: true,
    resources: true,
    heatmap: true,
    route: true,
  });

  const route = useRouteStore((state) => state.route);

  useEffect(() => {
    const setMaps = useSystemHealthStore.getState().setMaps;
    setMaps(hasToken ? "ONLINE" : "DEGRADED");
  }, [hasToken]);

  const validZones = useMemo(
    () =>
      zones.filter(
        (zone) => Number.isFinite(zone.centroid_lat) && Number.isFinite(zone.centroid_lng),
      ),
    [zones],
  );

  const incidentsQuery = useQuery({
    queryKey: ["map-incidents"],
    queryFn: () =>
      incidentsApi.list({ active_only: true, limit: 200 }).then((r) => r.data),
    enabled: hasToken,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });

  const resourcesQuery = useQuery({
    queryKey: ["map-resources"],
    queryFn: () => resourcesApi.list({}).then((r) => r.data),
    enabled: hasToken,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });

  const heatmapQuery = useQuery({
    queryKey: ["map-heatmap"],
    queryFn: () => heatmapsApi.combined().then((r) => r.data),
    enabled: hasToken,
    staleTime: 60_000,
    refetchInterval: 180_000,
    retry: 1,
  });

  const zoneById = useMemo(() => {
    const map = new Map<string, Zone>();
    zones.forEach((zone) => map.set(zone.zone_id, zone));
    return map;
  }, [zones]);

  const incidentsGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => {
    const features: GeoJSON.Feature[] = [];
    (incidentsQuery.data?.incidents ?? []).forEach((incident) => {
      const zone = zoneById.get(incident.zone_id);
      const lat = Number.isFinite(incident.lat) ? incident.lat : zone?.centroid_lat;
      const lng = Number.isFinite(incident.lng) ? incident.lng : zone?.centroid_lng;
      if (!Number.isFinite(lat as number) || !Number.isFinite(lng as number)) return;
      features.push({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [lng as number, lat as number],
        },
        properties: {
          id: incident.incident_id,
          priority: incident.priority_score ?? 0,
          disaster: incident.disaster_type ?? "—",
          victims: incident.victim_count ?? 0,
        },
      });
    });
    return { type: "FeatureCollection", features };
  }, [incidentsQuery.data, zoneById]);

  const resourcesGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => {
    const features: GeoJSON.Feature[] = [];
    (resourcesQuery.data?.resources ?? []).forEach((resource) => {
      if (!Number.isFinite(resource.lat) || !Number.isFinite(resource.lng)) return;
      features.push({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [resource.lng as number, resource.lat as number],
        },
        properties: {
          id: resource.resource_id,
          name: resource.name,
          type: resource.resource_type,
          available: resource.available ? 1 : 0,
        },
      });
    });
    return { type: "FeatureCollection", features };
  }, [resourcesQuery.data]);

  // Combined heatmap cells carry zone_id but no coordinates — join to centroids.
  const heatmapGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => {
    const features: GeoJSON.Feature[] = [];
    (heatmapQuery.data?.cells ?? []).forEach((cell: {
      zone_id: string;
      priority_score?: number | null;
      victim_density?: number | null;
    }) => {
      const zone = zoneById.get(cell.zone_id);
      if (!zone) return;
      const weight = cell.priority_score ?? cell.victim_density ?? 0;
      features.push({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [zone.centroid_lng, zone.centroid_lat],
        },
        properties: { weight: Math.max(0, Number(weight) || 0) },
      });
    });
    return { type: "FeatureCollection", features };
  }, [heatmapQuery.data, zoneById]);

  const routeGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => {
    const geometry = route?.geometry;
    if (!route || !geometry?.coordinates?.length) return EMPTY_GEOJSON;
    return {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry,
          properties: {
            source: route.source ?? "unknown",
            km: route.primary_route?.distance_km ?? 0,
          },
        },
      ],
    };
  }, [route]);

  useEffect(() => {
    if (!containerRef.current || !hasToken || mapRef.current) return;

    mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: DEFAULT_CENTER,
      zoom: 11,
      attributionControl: true,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      if (!layersAddedRef.current) {
        addDataLayers(map);
        layersAddedRef.current = true;
      }
      setMapReady(true);
    });

    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      layersAddedRef.current = false;
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, [hasToken]);

  // Feed layer sources once the map is ready.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const set = (key: string, data: GeoJSON.FeatureCollection) => {
      const source = map.getSource(key) as mapboxgl.GeoJSONSource | undefined;
      source?.setData(data);
    };
    set(LAYER_IDS.incidents, incidentsGeoJSON);
    set(LAYER_IDS.resources, resourcesGeoJSON);
    set(LAYER_IDS.heatmap, heatmapGeoJSON);
    set(LAYER_IDS.route, routeGeoJSON);
  }, [mapReady, incidentsGeoJSON, resourcesGeoJSON, heatmapGeoJSON, routeGeoJSON]);

  // Layer visibility toggles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    (Object.keys(LAYER_IDS) as LayerKey[]).forEach((key) => {
      const visibility = visible[key] ? "visible" : "none";
      if (map.getLayer(LAYER_IDS[key])) {
        map.setLayoutProperty(LAYER_IDS[key], "visibility", visibility);
      }
    });
  }, [mapReady, visible]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !validZones.length) return;

    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = validZones.map((zone) => {
      const priority = zone.priority_score ?? 0;
      const color = priority >= 70 ? "#ff6b6b" : priority >= 40 ? "#f3b562" : "#38d9c4";
      const element = document.createElement("button");
      element.type = "button";
      element.title = `${zone.name || "Zone"}: priority ${priority}/100`;
      element.style.cssText = `width:18px;height:18px;border:3px solid #fff;border-radius:50%;background:${color};box-shadow:0 0 0 7px ${color}33,0 0 18px ${color};cursor:pointer;`;
      element.onclick = () => onSelectZone(zone.zone_id);
      const popup = new mapboxgl.Popup({ offset: 14, closeButton: false }).setHTML(
        `<strong>${zone.name || "Operational zone"}</strong><br/>Priority ${priority}/100<br/>${zone.victim_count ?? 0} victims detected`
      );
      return new mapboxgl.Marker({ element })
        .setLngLat([zone.centroid_lng, zone.centroid_lat])
        .setPopup(popup)
        .addTo(map);
    });

    const bounds = new mapboxgl.LngLatBounds();
    validZones.forEach((zone) => bounds.extend([zone.centroid_lng, zone.centroid_lat]));
    if (selectedZone) {
      const zone = validZones.find((item) => item.zone_id === selectedZone);
      if (zone) map.flyTo({ center: [zone.centroid_lng, zone.centroid_lat], zoom: 13, duration: 800 });
    } else if (validZones.length > 1) {
      map.fitBounds(bounds, { padding: 70, maxZoom: 12, duration: 700 });
    } else {
      map.setCenter([validZones[0].centroid_lng, validZones[0].centroid_lat]);
      map.setZoom(12);
    }
  }, [validZones, selectedZone, onSelectZone]);

  if (!hasToken) {
    return (
      <div
        className="ops-map flex items-center justify-center p-8 text-center"
        style={{ height: mapHeight }}
        role="status"
      >
        <div className="max-w-md">
          <div className="ops-kicker mb-2">Map configuration required</div>
          <div className="ops-title mb-2">Live geographic visualization needs a Mapbox public token</div>
          <p className="text-sm leading-6 text-slate-400">
            Mapbox public token is not configured for this deployment. Zone coordinates
            still load from the backend — only the basemap is unavailable.
          </p>
          <div className="ops-mono mt-4 space-y-1 text-left text-xs text-slate-500">
            <div>Deployment: Vercel</div>
            <div>
              Required variable:{" "}
              <span className="text-[#38d9c4]">VITE_MAPBOX_TOKEN</span>
            </div>
            <div>Location: Project → Settings → Environment Variables</div>
          </div>
          <button
            type="button"
            className="ops-button ops-button-sm mt-4"
            onClick={() => window.location.reload()}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full" style={{ height: mapHeight }}>
      <div
        ref={containerRef}
        className="absolute inset-0"
        aria-label="Live operational map"
      />

      {/* Layer toggles (Phase 15) */}
      <div className="absolute bottom-3 left-3 z-10 rounded-xl border border-white/10 bg-[#0b1220]/90 p-2.5 backdrop-blur-sm">
        <div className="ops-kicker mb-1.5">Layers</div>
        <div className="space-y-1">
          {(Object.keys(LAYER_IDS) as LayerKey[]).map((key) => (
            <label
              key={key}
              className="flex cursor-pointer items-center gap-2 text-xs text-slate-300 hover:text-white"
            >
              <input
                type="checkbox"
                checked={visible[key]}
                onChange={(event) =>
                  setVisible((prev) => ({ ...prev, [key]: event.target.checked }))
                }
                className="h-3.5 w-3.5 accent-[#38d9c4]"
              />
              {LAYER_LABELS[key]}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
};
