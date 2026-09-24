import React from "react";
import { useQuery } from "@tanstack/react-query";

import { incidentsApi, type Incident } from "@/services/api";

interface LiveIncidentsPanelProps {
  selectedZone: string | null;
}

export const LiveIncidentsPanel: React.FC<LiveIncidentsPanelProps> = ({
  selectedZone,
}) => {
  const { data: incidents = [], isLoading } = useQuery<Incident[]>({
    queryKey: ["incidents", selectedZone],
    queryFn: async () => {
      const res = selectedZone
        ? await incidentsApi.list({ zone_id: selectedZone })
        : await incidentsApi.list();
      return res.data.incidents || [];
    },
    enabled: !!selectedZone,
  });

  return (
    <div className="p-4 bg-gray-800/50 rounded-lg h-fit">
      <h3 className="font-medium text-white mb-3">Active Incidents</h3>
      {isLoading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : incidents.length === 0 ? (
        <p className="text-sm text-gray-400">No active incidents</p>
      ) : (
        <div className="space-y-2 text-sm">
          {incidents.map((inc) => (
            <div key={inc.id} className="p-3 bg-gray-700/50 rounded-lg">
              <div className="font-medium text-white">
                {inc.disaster_type || "Unknown"}
                {inc.priority_score ? ` ${inc.priority_score}/100` : ""}
              </div>
              <div className="text-xs text-gray-300">
                Zone: {inc.zone_id || "N/A"} Victims: {inc.victim_count || 0}{" "}
                Status: {inc.status || "active"}
                {inc.lat != null && inc.lng != null &&
                  ` | ${inc.lat.toFixed(4)}, ${inc.lng.toFixed(4)}`}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};