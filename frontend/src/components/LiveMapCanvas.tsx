import { useEffect, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN } from "../lib/config";

interface MarkerData {
  x: number;
  y: number;
  c: string;
  label: string;
}

interface LiveMapCanvasProps {
  mapLayer: string;
  markers?: MarkerData[];
  freshness?: string;
}

const CENTER: [number, number] = [72.5714, 23.0225];
const LNG_SPAN = 0.45;
const LAT_SPAN = 0.26;

function svgToLngLat(x: number, y: number): [number, number] {
  const lng = CENTER[0] + (x - 450) * (LNG_SPAN / 900);
  const lat = CENTER[1] - (y - 260) * (LAT_SPAN / 520);
  return [lng, lat];
}

function createMarkerElement(color: string): HTMLDivElement {
  const el = document.createElement("div");
  el.style.width = "14px";
  el.style.height = "14px";
  el.style.borderRadius = "50%";
  el.style.backgroundColor = color;
  el.style.border = "2px solid rgba(255,255,255,0.85)";
  el.style.boxShadow = `0 0 8px ${color}`;
  return el;
}

export default function LiveMapCanvas({ mapLayer, markers = [], freshness = "8" }: LiveMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markerRefs = useRef<mapboxgl.Marker[]>([]);

  useEffect(() => {
    if (!MAPBOX_TOKEN || !containerRef.current) return;

    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: CENTER,
      zoom: 11,
    });
    mapRef.current = map;

    return () => {
      markerRefs.current.forEach((m) => m.remove());
      markerRefs.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markerRefs.current.forEach((m) => m.remove());
    markerRefs.current = [];

    markers.forEach((marker) => {
      const popup = new mapboxgl.Popup({ offset: 18 }).setText(marker.label);
      const m = new mapboxgl.Marker({ element: createMarkerElement(marker.c) })
        .setLngLat(svgToLngLat(marker.x, marker.y))
        .setPopup(popup)
        .addTo(map);
      markerRefs.current.push(m);
    });
  }, [markers]);

  if (!MAPBOX_TOKEN) {
    return (
      <div className="flex h-[420px] items-center justify-center bg-[#091827] text-sm text-slate-500">
        Mapbox token not configured
      </div>
    );
  }

  return (
    <div className="relative h-[420px]">
      <div ref={containerRef} className="h-full w-full" />
      <div className="absolute right-3 top-3 rounded-lg border border-line bg-[#07111f]/90 px-3 py-2 text-[10px] text-slate-400">
        {mapLayer} layer · Updated {freshness} sec ago
      </div>
    </div>
  );
}
