import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { zonesApi, incidentsApi, type Zone } from "@/services/api";
import { AppShell } from "@/components/AppShell";
import { WhatIfSimulation } from "@/components/WhatIfSimulation";
import { EmptyState, LoadingState } from "@/components/ui";

export const PredictionsPage: React.FC = () => {
  const [zoneId, setZoneId] = useState<string>("");

  const { data: zoneResponse, isLoading: loadingZones } = useQuery<{ zones: Zone[] }>({
    queryKey: ["zones"],
    queryFn: async () => (await zonesApi.withPriority()).data,
  });
  const zones = zoneResponse?.zones ?? [];

  const activeZoneId = zoneId || zones[0]?.zone_id || "";

  const { data: incident } = useQuery({
    queryKey: ["incidents", "for-prediction", activeZoneId],
    queryFn: async () => {
      const res = await incidentsApi.list({ zone_id: activeZoneId, active_only: true, limit: 1 });
      return res.data.incidents?.[0] ?? null;
    },
    enabled: Boolean(activeZoneId),
  });

  const selectedZone = zones.find((z) => z.zone_id === activeZoneId);

  return (
    <AppShell>
      <section className="fade-in mb-6">
        <div className="ops-kicker mb-2">Forecast</div>
        <h1 className="text-3xl font-bold tracking-tight">Predictions & what-if</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          Run flood and fire scenarios against live zone state. Simulations never dispatch
          resources — they only re-rank priority for commander review.
        </p>
      </section>

      <div className="ops-panel mb-5 flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="ops-kicker mb-1">Target zone</div>
          <div className="text-sm text-slate-300">
            {selectedZone?.name || "Select a zone to simulate"}
          </div>
        </div>
        <select
          className="ops-select sm:min-w-[280px]"
          value={activeZoneId}
          onChange={(e) => setZoneId(e.target.value)}
          aria-label="Select zone for prediction"
          disabled={loadingZones || zones.length === 0}
        >
          {zones.map((z) => (
            <option key={z.zone_id} value={z.zone_id}>
              {z.name || z.zone_id.slice(0, 8)} · {z.priority_score ?? 0}/100
            </option>
          ))}
        </select>
      </div>

      {loadingZones ? (
        <div className="ops-panel">
          <LoadingState label="Loading zones…" />
        </div>
      ) : !activeZoneId ? (
        <div className="ops-panel">
          <EmptyState title="No zone" message="No operational zones available for simulation." />
        </div>
      ) : (
        <div className="ops-panel">
          <div className="ops-panel-header">
            <div>
              <div className="ops-kicker">Simulation</div>
              <div className="ops-title">What-if engine</div>
            </div>
          </div>
          <div className="ops-panel-body">
            <WhatIfSimulation
              zoneId={activeZoneId}
              incidentId={incident?.incident_id}
              disasterType={incident?.disaster_type || "flood"}
            />
          </div>
        </div>
      )}
    </AppShell>
  );
};
