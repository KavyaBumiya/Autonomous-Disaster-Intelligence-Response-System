import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";

import { incidentsApi, reportsApi } from "@/services/api";

interface LiveIncidentsPanelProps {
  selectedZone: string | null;
}

interface Incident {
  incident_id: string;
  disaster_type?: string;
  priority_score?: number;
  zone_id?: string;
  victim_count?: number;
  status?: string;
  lat?: number;
  lng?: number;
}

export const LiveIncidentsPanel: React.FC<LiveIncidentsPanelProps> = ({
  selectedZone,
}) => {
  const { data = [], isLoading } = useQuery<Incident[]>({
    queryKey: ["incidents", selectedZone],
    queryFn: async () => {
      if (!selectedZone) {
        const res = await incidentsApi.list();
        return res.data.data.incidents || [];
      }
      const res = await incidentsApi.list({ zone_id: selectedZone });
      return res.data.data.incidents || [];
    },
    enabled: !!selectedZone,
  });

  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (data && data.length > 0) {
      setIncidents(data);
      setLoading(false);
    }
  }, [data]);

  useEffect(() => {
    if (loading && data?.length === 0 && !isLoading) {
      toast.info("No active incidents at this zone");
      setLoading(false);
    }
  }, [loading, data, isLoading]);

  return (
    <div className="p-4 bg-gray-800/50 rounded-lg h-fit">
      <h3 className="font-medium text-white mb-3">Active Incidents</h3>
      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : incidents.length === 0 ? (
        <p className="text-sm text-gray-400">No active incidents</p>
      ) : (
        <div className="space-y-2 text-sm">
          {incidents.map((inc) => (
            <div key={inc.incident_id} className="p-3 bg-gray-700/50 rounded-lg">
              <div className="font-medium text-white">
                {inc.disaster_type || "Unknown"} {inc.priority_score ? ` ${inc.priority_score}/100` : ""}
              </div>
              <div className="text-xs text-gray-300">
                Zone: {inc.zone_id || "N/A"} 
                Victims: {inc.victim_count || 0} 
                Status: {inc.status || "active"}
                {inc.lat && inc.lng && ` | ${inc.lat.toFixed(4)}, ${inc.lng.toFixed(4)}`}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};