import React, { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";

interface CriticalZone3DProps {
  zoneId: string;
}

interface Zone {
  id?: string;
  name?: string;
  centroid_lat: number;
  centroid_lng: number;
  priority_score?: number;
  victim_count?: number;
}

interface Incident {
  id?: string;
  name?: string;
  priority_score?: number;
  status?: string;
}

export const CriticalZone3D: React.FC<CriticalZone3DProps> = ({
  zoneId,
}) => {
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
      const res = await axios.get<Zone>(`/api/zones/${zoneId}`);
      return res.data;
    },
    enabled: Boolean(zoneId),
  });

  // Fetch incident data for this zone
  const {
    data: incident,
    isLoading: isIncidentLoading,
  } = useQuery<Incident>({
    queryKey: ["incident", zoneId],
    queryFn: async () => {
      const res = await axios.get<Incident>(`/api/incidents/${zoneId}`);
      return res.data;
    },
    enabled: Boolean(zoneId),
  });

  useEffect(() => {
    if (!show3D || !zone || !mapContainerRef.current) {
      return;
    }

    const token = import.meta.env.VITE_MAPBOX_TOKEN;

    if (!token) {
      console.error("VITE_MAPBOX_TOKEN is not configured.");
      setShow3D(false);
      return;
    }

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
  }, [show3D, zone]);

  const toggleView = () => {
    setShow3D((prev: boolean) => !prev);
  };

  if (isZoneLoading || isIncidentLoading) {
    return (
      <div className="p-6 bg-gray-800/50 rounded-lg h-fit">
        <p className="text-gray-300">
          Loading zone data...
        </p>
      </div>
    );
  }

  if (!zone) {
    return (
      <div className="p-6 bg-gray-800/50 rounded-lg">
        <p className="text-red-400">
          Unable to load zone data.
        </p>
      </div>
    );
  }

  if (!show3D) {
    return (
      <div className="p-4 bg-gray-800/50 rounded-lg mb-4">
        <h3 className="font-medium text-white mb-2">
          Critical Zone Viewer
        </h3>

        <p className="text-sm text-gray-300">
          Zone: {zone.name || "Unknown"}
        </p>

        <p className="text-sm text-gray-300">
          Priority: {zone.priority_score ?? 0}/100
        </p>

        {incident && (
          <p className="text-sm text-gray-400 mt-1">
            Incident: {incident.name || incident.id || "Active incident"}
          </p>
        )}

        <button
          onClick={() => setShow3D(true)}
          className="mt-3 bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-500 text-sm"
        >
          Open 3D View
        </button>
      </div>
    );
  }

  return (
    <div className="relative h-[600px] w-full rounded-lg overflow-hidden">
      <div
        ref={mapContainerRef}
        className="h-full w-full"
      />

      <div className="absolute bottom-4 left-4 flex gap-2">
        <button
          onClick={toggleView}
          className="bg-gray-700 text-white px-3 py-1 rounded text-sm hover:bg-gray-600"
          title="Switch to 2D Map"
        >
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
          className="bg-green-600 text-white px-3 py-1 rounded text-sm hover:bg-green-500"
          title="Fly to Center"
        >
          Center
        </button>
      </div>

      <div className="absolute top-4 left-4 bg-gray-900/80 text-white px-3 py-2 rounded-lg">
        <div className="font-medium">
          {zone.name || "Critical Zone"}
        </div>

        <div className="text-xs text-gray-300">
          Priority: {zone.priority_score ?? 0}/100
          {zone.victim_count && `, ${zone.victim_count} victims`}
        </div>
      </div>
    </div>
  );
};