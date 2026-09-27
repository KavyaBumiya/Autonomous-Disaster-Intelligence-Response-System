import React, { useEffect, useRef, useState } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { useQuery } from "@tanstack/react-query";
import api from "@/services/api";

Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_ION_TOKEN || "";

interface CesiumGlobeProps {
  zones?: Array<{
    zone_id: string;
    name: string;
    centroid_lat: number;
    centroid_lng: number;
    priority_score: number;
    victim_count: number;
  }>;
  onSelectZone?: (zoneId: string) => void;
  height?: string;
}

export const CesiumGlobe: React.FC<CesiumGlobeProps> = ({
  zones = [],
  onSelectZone,
  height = "clamp(400px, 60vh, 700px)",
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;
    if (!Cesium.Ion.defaultAccessToken) {
      setError("Cesium Ion token not configured");
      return;
    }

    let viewer: Cesium.Viewer;
    try {
      viewer = new Cesium.Viewer(containerRef.current, {
        terrain: Cesium.Terrain.fromWorldTerrain(),
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
      setError(err instanceof Error ? err.message : "Cesium init failed");
      return;
    }

    viewerRef.current = viewer;
    setReady(true);

    return () => {
      viewer.destroy();
      viewerRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;

    viewer.entities.removeAll();

    zones.forEach((zone) => {
      if (!Number.isFinite(zone.centroid_lat) || !Number.isFinite(zone.centroid_lng)) return;
      const priority = zone.priority_score ?? 0;
      const color =
        priority >= 70
          ? Cesium.Color.RED.withAlpha(0.8)
          : priority >= 40
            ? Cesium.Color.ORANGE.withAlpha(0.8)
            : Cesium.Color.CYAN.withAlpha(0.8);

      viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(zone.centroid_lng, zone.centroid_lat),
        point: {
          pixelSize: Math.max(8, Math.min(24, priority / 4 + 8)),
          color,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
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
        },
        properties: {
          zone_id: zone.zone_id,
        },
      });
    });

    if (zones.length > 0) {
      const first = zones[0];
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(
          first.centroid_lng,
          first.centroid_lat,
          50000,
        ),
        duration: 1.5,
      });
    }
  }, [zones, ready]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready || !onSelectZone) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click: { position: Cesium.Cartesian2 }) => {
      const picked = viewer.scene.pick(click.position);
      if (
        Cesium.defined(picked) &&
        picked.id &&
        picked.id.properties &&
        picked.id.properties.zone_id
      ) {
        const zoneId = picked.id.properties.zone_id.getValue();
        onSelectZone(zoneId);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => handler.destroy();
  }, [ready, onSelectZone]);

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
            Set VITE_CESIUM_ION_TOKEN to enable 3D visualization
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
    </div>
  );
};
