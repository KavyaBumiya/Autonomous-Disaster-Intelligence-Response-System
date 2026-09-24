import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { zonesApi, heatmapsApi, type Zone } from "@/services/api";
import { AppShell } from "@/components/AppShell";
import { Button, EmptyState, LoadingState, PriorityBadge } from "@/components/ui";

interface HeatmapPayload {
  [key: string]: unknown;
}

export const HeatmapsPage: React.FC = () => {
  const navigate = useNavigate();
  const [zoneId, setZoneId] = useState<string>("");

  const { data: zoneResponse, isLoading: loadingZones } = useQuery<{ zones: Zone[] }>({
    queryKey: ["zones"],
    queryFn: async () => (await zonesApi.withPriority()).data,
  });
  const zones = zoneResponse?.zones ?? [];

  const activeZoneId = zoneId || zones[0]?.zone_id || "";

  const { data: heatmap, isLoading, isError } = useQuery<HeatmapPayload>({
    queryKey: ["heatmap", activeZoneId],
    queryFn: async () => (await heatmapsApi.combined(activeZoneId || undefined)).data,
    enabled: Boolean(activeZoneId) || zones.length >= 0,
  });

  const selectedZone = zones.find((z) => z.zone_id === activeZoneId);
  const entries = heatmap ? Object.entries(heatmap).slice(0, 12) : [];

  return (
    <AppShell>
      <section className="fade-in mb-6">
        <div className="ops-kicker mb-2">Spatial risk</div>
        <h1 className="text-3xl font-bold tracking-tight">Heatmaps</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          Combined density layers for reports, victims, and priority. Open the dashboard with the
          heatmap layer enabled for the live map view.
        </p>
      </section>

      <div className="ops-panel mb-5 flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="ops-select sm:min-w-[280px]"
            value={activeZoneId}
            onChange={(e) => setZoneId(e.target.value)}
            aria-label="Select zone for heatmap"
            disabled={loadingZones || zones.length === 0}
          >
            {zones.map((z) => (
              <option key={z.zone_id} value={z.zone_id}>
                {z.name || z.zone_id.slice(0, 8)}
              </option>
            ))}
          </select>
          {selectedZone && <PriorityBadge score={selectedZone.priority_score} />}
        </div>
        <Button
          variant="primary"
          disabled={!activeZoneId}
          onClick={() => navigate(`/dashboard/${activeZoneId}`)}
        >
          Open on live map
        </Button>
      </div>

      <div className="ops-panel">
        <div className="ops-panel-header">
          <div>
            <div className="ops-kicker">Combined layer</div>
            <div className="ops-title">{selectedZone?.name || "All zones"}</div>
          </div>
        </div>
        {isLoading ? (
          <LoadingState label="Loading heatmap…" />
        ) : isError ? (
          <EmptyState title="Unavailable" message="Heatmap endpoint returned an error." />
        ) : entries.length === 0 ? (
          <EmptyState title="No data" message="No heatmap cells for this zone." />
        ) : (
          <div className="ops-resource-grid p-4">
            {entries.map(([key, value]) => (
              <div key={key} className="ops-stat" style={{ minHeight: 96 }}>
                <div className="ops-stat-label ops-truncate" title={key}>
                  {key}
                </div>
                <div className="ops-mono mt-2 break-words text-sm text-slate-200">
                  {typeof value === "object" && value !== null
                    ? JSON.stringify(value).slice(0, 80)
                    : String(value).slice(0, 80)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
};
