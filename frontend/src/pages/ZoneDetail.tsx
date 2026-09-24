import React, { Suspense, lazy, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { zonesApi, incidentsApi } from "@/services/api";
import { WhatIfSimulation } from "../components/WhatIfSimulation";
import { RouteIntelligence } from "../components/RouteIntelligence";
import { ResourcePanel } from "../components/ResourcePanel";
import { LiveIncidentsPanel } from "./LiveIncidentsPanel";

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

export const ZoneDetail: React.FC<ZoneDetailProps> = ({ zoneId }) => {
  const { incidentId } = useParams<{ incidentId: string }>();
  const [view, setView] = useState("overview");

  // Fetch zone when incident changes
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

  // Prefer parent prop, then zone resolved from incident
  const activeZoneId = zoneId ?? zone?.zone_id ?? null;

  // Fetch zone details when active zone changes
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

  return (
    <div>
      <main className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Panel: Live Panels */}
        <div className="lg:col-span-1 space-y-4">
          <LiveIncidentsPanel selectedZone={activeZoneId} />
          <ResourcePanel zoneId={activeZoneId} />
        </div>

        {/* Center Panel based on view */}
        <div className="lg:col-span-1 space-y-4">
          {view === "prediction" && activeZoneId ? (
            <WhatIfSimulation
              zoneId={activeZoneId}
              incidentId={incidentId || ""}
              disasterType={zone?.disaster_type || "flood"}
            />
          ) : view === "route" && activeZoneId ? (
            <RouteIntelligence zoneId={activeZoneId} incidentId={incidentId || ""} />
          ) : view === "resources" && activeZoneId ? (
            <ResourcePanel zoneId={activeZoneId} incidentId={incidentId || ""} />
          ) : view === "3d" && activeZoneId ? (
            <Suspense fallback={<Zone3DFallback />}>
              <CriticalZone3D zoneId={activeZoneId} />
            </Suspense>
          ) : (
            <div>
              <div className="flex mb-3">
                <button
                  onClick={() => setView("overview")}
                  className={view === "overview" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
                >
                  Overview
                </button>
                <button
                  onClick={() => setView("prediction")}
                  className={view === "prediction" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
                >
                  What-If
                </button>
                <button
                  onClick={() => setView("route")}
                  className={view === "route" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
                >
                  Route Intelligence
                </button>
                <button
                  onClick={() => setView("3d")}
                  className={view === "3d" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
                >
                  3D View
                </button>
              </div>
              {activeZoneId ? (
                <p className="text-sm text-gray-400">
                  Select a view above for {zoneDetails?.name || "this zone"}.
                </p>
              ) : (
                <p className="text-sm text-gray-400">
                  Select an incident to begin monitoring.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Right Panel: 3D View or expanded details */}
        <div className="lg:col-span-1 space-y-4">
          {activeZoneId ? (
            <>
              <button
                onClick={() => setView("3d")}
                className="w-full bg-purple-600 text-white mb-3 rounded-lg py-2 text-sm hover:bg-purple-500"
              >
                Open Full 3D View
              </button>

              {view === "resources" ? (
                <ResourcePanel zoneId={activeZoneId} incidentId={incidentId || ""} />
              ) : null}

              {view === "prediction" ? (
                <WhatIfSimulation
                  zoneId={activeZoneId}
                  incidentId={incidentId || ""}
                  disasterType={zone?.disaster_type || "flood"}
                />
              ) : null}
              {view === "route" ? (
                <RouteIntelligence zoneId={activeZoneId} incidentId={incidentId || ""} />
              ) : null}
            </>
          ) : null}
        </div>
      </main>
    </div>
  );
};