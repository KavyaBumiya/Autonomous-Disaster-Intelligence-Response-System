import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { incidentsApi, type Incident } from "@/services/api";
import { Badge, EmptyState, LoadingState, PriorityBadge } from "@/components/ui";

interface LiveIncidentsPanelProps {
  selectedZone: string | null;
}

export const LiveIncidentsPanel: React.FC<LiveIncidentsPanelProps> = ({
  selectedZone,
}) => {
  const navigate = useNavigate();
  const { data: incidents = [], isLoading, isError } = useQuery<Incident[]>({
    queryKey: ["incidents", selectedZone],
    queryFn: async () => {
      const res = selectedZone
        ? await incidentsApi.list({ zone_id: selectedZone, active_only: true })
        : await incidentsApi.list({ active_only: true });
      return res.data.incidents || [];
    },
    refetchInterval: 30000,
  });

  return (
    <div className="ops-panel">
      <div className="ops-panel-header">
        <div>
          <div className="ops-kicker">Live</div>
          <div className="ops-title-sm">Active incidents</div>
        </div>
        <Badge tone={incidents.length ? "red" : "slate"}>
          {incidents.length} open
        </Badge>
      </div>
      <div className="ops-scroll-y" style={{ maxHeight: 280 }}>
        {isLoading ? (
          <LoadingState label="Loading incidents…" />
        ) : isError ? (
          <EmptyState title="Unavailable" message="Could not load incidents." />
        ) : incidents.length === 0 ? (
          <EmptyState title="All clear" message="No active incidents in this view." />
        ) : (
          incidents.map((inc) => (
            <button
              key={inc.incident_id}
              type="button"
              className="ops-list-item w-full text-left"
              onClick={() => navigate(`/incidents/${inc.incident_id}`)}
            >
              <span className="min-w-0 flex-1">
                <span className="ops-truncate block text-sm font-semibold text-white">
                  {inc.disaster_type || "Unknown"}
                </span>
                <span className="ops-mono mt-1 block text-xs text-slate-400">
                  {inc.zone_id?.slice(0, 8) || "—"} · {inc.victim_count || 0} victims ·{" "}
                  {inc.status || "active"}
                </span>
              </span>
              <PriorityBadge score={inc.priority_score} band={inc.priority_band} />
            </button>
          ))
        )}
      </div>
    </div>
  );
};
