import React, { useEffect, useMemo, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import type { Zone } from "@/services/api";

interface OperationalMapProps {
  zones: Zone[];
  selectedZone: string | null;
  onSelectZone: (zoneId: string) => void;
}

const DEFAULT_CENTER: [number, number] = [73.1812, 22.3072];

export const OperationalMap: React.FC<OperationalMapProps> = ({
  zones,
  selectedZone,
  onSelectZone,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<mapboxgl.Marker[]>([]);
  const hasToken = Boolean(import.meta.env.VITE_MAPBOX_TOKEN && import.meta.env.VITE_MAPBOX_TOKEN !== "your_mapbox_access_token_here");

  const validZones = useMemo(
    () => zones.filter((zone) => Number.isFinite(zone.centroid_lat) && Number.isFinite(zone.centroid_lng)),
    [zones]
  );

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

    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [hasToken]);

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
      <div className="ops-map flex min-h-[380px] items-center justify-center p-8 text-center">
        <div className="max-w-md">
          <div className="ops-kicker mb-2">Map configuration required</div>
          <div className="ops-title mb-2">Add a Mapbox public token</div>
          <p className="text-sm leading-6 text-slate-400">Set <span className="ops-mono text-[#38d9c4]">VITE_MAPBOX_TOKEN</span> in <span className="ops-mono text-[#38d9c4]">frontend/.env</span> to enable the live geographic map. Zone data will be plotted from the backend coordinates.</p>
        </div>
      </div>
    );
  }

  return <div ref={containerRef} className="h-[440px] w-full" aria-label="Live operational map" />;
};
