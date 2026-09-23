import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { zonesApi, incidentsApi, predictionsApi, resourcesApi, commandApi } from "@/services/api";
import { WhatIfSimulation } from "../components/WhatIfSimulation";
import { RouteIntelligence } from "../components/RouteIntelligence";
import { ResourcePanel } from "../components/ResourcePanel";
import { LiveIncidentsPanel } from "./LiveIncidentsPanel";
import { CriticalZone3D } from "./CriticalZone3D";
import { DashboardLayout } from "./DashboardLayout";

interface ZoneDetailProps {
  zoneId?: string | null;
}

interface ZoneData {
  zone_id: string;
  disaster_type?: string;
}

export const ZoneDetail: React.FC<ZoneDetailProps> = ({ zoneId }) => {
  const { incidentId } = useParams<{ incidentId: string }>();
  const navigate = useNavigate();
  const [selectedZone, setSelectedZone] = useState<string | null>(zoneId ?? null);
  const [view, setView] = useState("overview"); // 'overview' | '3d' | 'resources' | 'prediction' | 'route'

  // Fetch zone when incident changes or manually select
  const { data: zone, isLoading, refetch } = useQuery<ZoneData | null>({
    queryKey: ["zone-detail", incidentId],
    queryFn: async () => {
      // If we have an incident ID, fetch its zone
      if (incidentId) {
        const res = await incidentsApi.get(incidentId);
        // Extract zone info from incident
        return {
          zone_id: res.data.data.zone_id,
          disaster_type: res.data.data.disaster_type,
        };
      }
      return null;
    },
    enabled: !!incidentId,
  });

  // When zone is loaded, select it
  useEffect(() => {
    if (zone?.zone_id && !selectedZone) {
      setSelectedZone(zone.zone_id);
    }
  }, [zone]);

  // Handle view change
  const handleViewChange = (viewName: string) => {
    setView(viewName);
  };

  // Fetch zone details when selectedZone changes
  const { data: zoneDetails, isLoading: loadingZone } = useQuery({
    queryKey: ["zone", selectedZone],
    queryFn: async () => {
      if (!selectedZone) return null;
      const res = await zonesApi.withPriority({ limit: 100 });
      const z = res.data.zones.find((z: any) => z.zone_id === selectedZone);
      return z ? {
        zone_id: z.zone_id,
        name: z.name,
        centroid_lat: z.centroid_lat,
        centroid_lng: z.centroid_lng,
        radius_meters: z.radius_meters,
        priority_score: z.priority_score,
        victim_count: z.victim_count,
      } : null;
    },
    enabled: !!selectedZone,
  });

  return (
    <div>
      <DashboardLayout initialZoneId={selectedZone ?? undefined}>
        {/* Override the main content area based on view */}
        <main className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Panel: Live Panels */}
          <div className="lg:col-span-1 space-y-4">
            <LiveIncidentsPanel selectedZone={selectedZone} />
            {/* RecentReportsPanel removed - using LiveIncidentsPanel */}
            <ResourcePanel zoneId={selectedZone} />
          </div>

          {/* Center Panel based on view */}
          <div className="lg:col-span-1 space-y-4">
            {view === "prediction" && selectedZone ? (
              <WhatIfSimulation
                zoneId={selectedZone}
                incidentId={incidentId || ""}
                disasterType={zone?.disaster_type || "flood"}
              />
            ) : view === "route" && selectedZone ? (
              <RouteIntelligence zoneId={selectedZone} incidentId={incidentId || ""} />
            ) : view === "resources" && selectedZone ? (
              <ResourcePanel zoneId={selectedZone} incidentId={incidentId || ""} />
            ) : view === "3d" && selectedZone ? (
              <CriticalZone3D zoneId={selectedZone} />
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
                {selectedZone ? (
                  <p className="text-sm text-gray-400">
                    Select a zone from the dashboard sidebar to begin monitoring.
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
            {selectedZone ? (
              <>
                {/* 3D View button in the panel */}
                <button
                  onClick={() => setView("3d")}
                  className="w-full bg-purple-600 text-white mb-3 rounded-lg py-2 text-sm hover:bg-purple-500"
                >
                  Open Full 3D View
                </button>

                {/* Resources tab */}
                {view === "resources" ? (
                  <ResourcePanel zoneId={selectedZone} incidentId={incidentId || ""} />
                ) : null}

                {/* Prediction tab */}
                {view === "prediction" && selectedZone ? (
                  <WhatIfSimulation
                    zoneId={selectedZone}
                    incidentId={incidentId || ""}
                    disasterType={zone?.disaster_type || "flood"}
                  />
                ) : null}
                {view === "route" && selectedZone ? (
                  <RouteIntelligence zoneId={selectedZone} incidentId={incidentId || ""} />
                ) : null}
              </>
            ) : null}
          </div>
        </main>
      </DashboardLayout>
    </div>
  );
};