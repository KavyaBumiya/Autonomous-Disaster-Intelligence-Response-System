import React, { Suspense, lazy, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { zonesApi, incidentsApi } from "@/services/api";
import { WhatIfSimulation } from "../components/WhatIfSimulation";
import { RouteIntelligence } from "../components/RouteIntelligence";
import { ResourcePanel } from "../components/ResourcePanel";
import { Button, PriorityBadge } from "@/components/ui";

const CriticalZone3D = lazy(() =>
  import("./CriticalZone3D").then((m) => ({ default: m.CriticalZone3D }))
);

const Zone3DFallback = () => (
  <div className="ops-panel flex min-h-[280px] items-center justify-center p-6 text-center">
    <div className="ops-kicker">Loading 3D view…</div>
  </div>
);

interface ZoneDetailProps {
  zoneId?: string | null;
}

interface ZoneData {
  zone_id: string;
  disaster_type?: string | null;
}

interface ZoneSummary {
  zone_id: string;
  name?: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_meters: number;
  priority_score?: number;
  victim_count?: number;
}

type ZoneView = "overview" | "prediction" | "route" | "resources" | "3d";

const TABS: Array<{ id: ZoneView; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "prediction", label: "What-If" },
  { id: "route", label: "Routes" },
  { id: "resources", label: "Resources" },
  { id: "3d", label: "3D" },
];

export const ZoneDetail: React.FC<ZoneDetailProps> = ({ zoneId }) => {
  const { incidentId } = useParams<{ incidentId: string }>();
  const navigate = useNavigate();
  const [view, setView] = useState<ZoneView>("overview");

  const { data: zone } = useQuery<ZoneData | null>({
    queryKey: ["zone-detail", incidentId],
    queryFn: async () => {
      if (incidentId) {
        const res = await incidentsApi.get(incidentId);
        return {
          zone_id: res.data.zone_id,
          disaster_type: res.data.disaster_type,
        };
      }
      return null;
    },
    enabled: !!incidentId,
  });

  const activeZoneId = zoneId ?? zone?.zone_id ?? null;

  const { data: zoneDetails } = useQuery<ZoneSummary | null>({
    queryKey: ["zone", activeZoneId],
    queryFn: async () => {
      if (!activeZoneId) return null;
      const res = await zonesApi.withPriority({ limit: 100 });
      const z = res.data.zones.find((candidate) => candidate.zone_id === activeZoneId);
      if (!z) return null;
      return {
        zone_id: z.zone_id,
        name: z.name,
        centroid_lat: z.centroid_lat,
        centroid_lng: z.centroid_lng,
        radius_meters: z.radius_meters,
        priority_score: z.priority_score,
        victim_count: z.victim_count,
      };
    },
    enabled: !!activeZoneId,
  });

  if (!activeZoneId) {
    return (
      <div className="ops-panel p-6">
        <div className="ops-kicker mb-2">Zone workspace</div>
        <div className="ops-title mb-2">No zone selected</div>
        <p className="text-sm text-slate-400">
          Select a zone on the map or from the zone dropdown to open reasoning tools.
        </p>
      </div>
    );
  }

  return (
    <div className="ops-panel">
      <div className="ops-panel-header flex-col gap-3 sm:flex-row">
        <div className="min-w-0">
          <div className="ops-kicker">Zone workspace</div>
          <div className="ops-title ops-truncate">
            {zoneDetails?.name || `Zone ${activeZoneId.slice(0, 8)}`}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {typeof zoneDetails?.priority_score === "number" && (
            <PriorityBadge score={zoneDetails.priority_score} />
          )}
          <Button size="sm" onClick={() => navigate(`/3d/${activeZoneId}`)}>
            Full 3D
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-[var(--line)] px-4 py-3" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={view === tab.id}
            onClick={() => setView(tab.id)}
            className={`ops-nav-link ${view === tab.id ? "active" : ""}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="ops-panel-body">
        {view === "prediction" ? (
          <WhatIfSimulation
            zoneId={activeZoneId}
            incidentId={incidentId || ""}
            disasterType={zone?.disaster_type || "flood"}
          />
        ) : view === "route" ? (
          <RouteIntelligence zoneId={activeZoneId} incidentId={incidentId || ""} />
        ) : view === "resources" ? (
          <ResourcePanel zoneId={activeZoneId} incidentId={incidentId || ""} />
        ) : view === "3d" ? (
          <Suspense fallback={<Zone3DFallback />}>
            <CriticalZone3D zoneId={activeZoneId} />
          </Suspense>
        ) : (
          <div className="space-y-4">
            <div className="ops-stat">
              <div className="ops-stat-label">Victims detected</div>
              <div className="ops-stat-value">{zoneDetails?.victim_count ?? "—"}</div>
              <div className="mt-2 text-xs text-slate-400">
                Radius {Math.round((zoneDetails?.radius_meters ?? 0) / 100) / 10} km ·{" "}
                {zone?.disaster_type || "typed incident"}
              </div>
            </div>
            <p className="text-sm leading-6 text-slate-400">
              Use the tabs above to run what-if simulations, compute response routes,
              review resource allocations, or open the digital twin in 3D.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
