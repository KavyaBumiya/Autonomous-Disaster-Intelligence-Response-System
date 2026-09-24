import React, { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useQuery } from "@tanstack/react-query";

import { zonesApi, incidentsApi, type Zone, type Incident } from "@/services/api";

interface CriticalZone3DProps {
  zoneId: string;
}

export const CriticalZone3D: React.FC<CriticalZone3DProps> = ({
  zoneId,
}) => {
  const hasMapboxToken = Boolean(import.meta.env.VITE_MAPBOX_TOKEN);
  const [show3D, setShow3D] = useState<boolean>(false);

  // HTML element that contains the Mapbox map
  const mapContainerRef = useRef<HTMLDivElement | null>(null);

  // Actual Mapbox map instance
  const mapInstanceRef = useRef<mapboxgl.Map | null>(null);

  // Fetch zone data
  const {
    data: zone,
    isLoading: isZoneLoading,
  } = useQuery<Zone>({
    queryKey: ["zone", zoneId],
    queryFn: async () => {
      const res = await zonesApi.get(zoneId);
      return res.data;
    },
    enabled: Boolean(zoneId),
  });

  // Fetch the first active incident for this zone (list endpoint, not get-by-id with zoneId)
  const {
    data: incident,
    isLoading: isIncidentLoading,
  } = useQuery<Incident | null>({
    queryKey: ["incident", "for-zone", zoneId],
    queryFn: async () => {
      const res = await incidentsApi.list({ zone_id: zoneId, active_only: true, limit: 1 });
      return res.data.incidents?.[0] ?? null;
    },
    enabled: Boolean(zoneId),
  });

  useEffect(() => {
    if (!show3D || !zone || !mapContainerRef.current) {
      return;
    }

    if (!hasMapboxToken) {
      console.error("VITE_MAPBOX_TOKEN is not configured.");
      return;
    }

    const token = import.meta.env.VITE_MAPBOX_TOKEN as string;
    mapboxgl.accessToken = token;

    // Prevent creating multiple Mapbox instances
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove();
      mapInstanceRef.current = null;
    }

    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/streets-v12",
      center: [zone.centroid_lng, zone.centroid_lat],
      zoom: 12,
      pitch: 70,
      bearing: 0,
      antialias: true,
    });

    mapInstanceRef.current = map;

    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    map.on("load", () => {
      // Add zone polygon source
      const lat = zone.centroid_lat;
      const lng = zone.centroid_lng;
      const offset = 0.01;

      const polygonCoordinates: [number, number][][] = [
        [
          [lng - offset, lat - offset],
          [lng + offset, lat - offset],
          [lng + offset, lat + offset],
          [lng - offset, lat + offset],
          [lng - offset, lat - offset],
        ],
      ];

      map.addSource("critical-zone", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {
            priority_score: zone.priority_score ?? 0,
            victim_count: zone.victim_count ?? 0,
          },
          geometry: {
            type: "Polygon",
            coordinates: polygonCoordinates,
          },
        },
      });

      // Enhanced fill-extrusion layer with priority-based height and color
      map.addLayer({
        id: "critical-zone-extrusion",
        type: "fill-extrusion",
        source: "critical-zone",
        paint: {
          "fill-extrusion-height": Math.max(
            50,
            (zone.priority_score ?? 0) * 5
          ),

          "fill-extrusion-base": 0,

          "fill-extrusion-color": [
            "interpolate",
            ["linear"],
            ["get", "priority_score"],
            0,
            "#22c55e",  // green - low priority
            30,
            "#f59e0b",  // orange - medium priority
            70,
            "#ef4444",  // red - high priority
          ],

          "fill-extrusion-opacity": 0.9,

        },
      });

      // Add building extrusions based on priority score
      // Higher priority = taller "buildings" in the zone
      if (zone.priority_score && zone.priority_score > 30) {
        const buildingCount = Math.min(
          Math.round(zone.priority_score / 10),
          20
        ); // 3-20 buildings based on priority

        for (let i = 0; i < buildingCount; i++) {
          const buildingLng =
            zone.centroid_lng +
            (Math.random() - 0.5) * 0.02; // random offset within ~200m
          const buildingLat =
            zone.centroid_lat +
            (Math.random() - 0.5) * 0.02;

          map.addSource(`building-${i}`, {
            type: "geojson",
            data: {
              type: "Feature",
              geometry: {
                type: "Point",
                coordinates: [buildingLng, buildingLat],
              },
              properties: {
                height: Math.random() * (zone.priority_score ?? 0) * 0.5 + 20,
                color: [
                  "interpolate",
                  ["linear"],
                  ["get", "priority_score"],
                  0,
                  "#8b5cf6",
                  50,
                  "#ec4899",
                  100,
                  "#ef4444",
                ],
              },
            },
          });

          map.addLayer({
            id: `building-layer-${i}`,
            type: "circle",
            source: `building-${i}`,
            paint: {
              "circle-radius": 8,
              "circle-color": "#a5f3fc",
              "circle-stroke-color": "#1e293b",
              "circle-stroke-width": 1,
            },
          });
        }
      }

      // Fly to the zone center
      map.flyTo({
        center: [zone.centroid_lng, zone.centroid_lat],
        zoom: 15,
        pitch: 70,
        duration: 1500,
      });
    });

    const handleResize = () => {
      map.resize();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);

      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [show3D, zone, hasMapboxToken]);

  const toggleView = () => {
    if (!hasMapboxToken && !show3D) {
      console.error("VITE_MAPBOX_TOKEN is not configured.");
      return;
    }
    setShow3D((prev: boolean) => !prev);
  };

  if (isZoneLoading || isIncidentLoading) {
    return (
      <div className="ops-panel p-6">
        <div className="ops-kicker mb-2">Digital twin</div>
        <p className="text-sm text-slate-400">Loading zone data…</p>
        <div className="skeleton mt-3 h-32 w-full" />
      </div>
    );
  }

  if (!zone) {
    return (
      <div className="ops-panel p-6">
        <div className="ops-kicker mb-2" style={{ color: "var(--red)" }}>
          Digital twin error
        </div>
        <p className="text-sm text-slate-400">Unable to load zone data.</p>
      </div>
    );
  }

  if (!show3D) {
    return (
      <div className="ops-panel p-4">
        <div className="ops-kicker mb-2">Critical zone viewer</div>
        <p className="text-sm text-slate-300">Zone: {zone.name || "Unknown"}</p>
        <p className="ops-mono text-sm text-slate-300">Priority: {zone.priority_score ?? 0}/100</p>
        {incident && (
          <p className="mt-1 text-xs text-slate-400">
            Incident: {incident.disaster_type || incident.incident_id} ({incident.priority_score}/100)
          </p>
        )}
        <button
          onClick={toggleView}
          disabled={!hasMapboxToken}
          className="ops-button ops-button-primary mt-3"
        >
          Open 3D view
        </button>
        {!hasMapboxToken && (
          <p className="mt-2 text-xs text-[#f3b562]">
            Mapbox token missing — set VITE_MAPBOX_TOKEN to enable 3D view.
          </p>
        )}
      </div>
    );
  }

  return (
    <div
      className="relative w-full overflow-hidden rounded-[var(--radius-lg)]"
      style={{ height: "clamp(420px, 60vh, 720px)" }}
    >
      <div ref={mapContainerRef} className="h-full w-full" />

      <div className="absolute bottom-4 left-4 flex gap-2">
        <button onClick={toggleView} className="ops-button ops-button-sm" title="Switch to 2D map">
          2D
        </button>
        <button
          onClick={() => {
            mapInstanceRef.current?.flyTo({
              center: [zone.centroid_lng, zone.centroid_lat],
              zoom: 15,
              pitch: 70,
              duration: 1000,
            });
          }}
          className="ops-button ops-button-primary ops-button-sm"
          title="Fly to center"
        >
          Center
        </button>
      </div>

      <div className="ops-panel absolute left-4 top-4 px-3 py-2" style={{ background: "rgba(7,16,28,.85)" }}>
        <div className="text-sm font-semibold">{zone.name || "Critical zone"}</div>
        <div className="ops-mono text-xs text-slate-300">
          Priority {zone.priority_score ?? 0}/100
          {zone.victim_count ? `, ${zone.victim_count} victims` : ""}
        </div>
      </div>
    </div>
  );
};
