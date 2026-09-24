import React from "react";
import { useQuery } from "@tanstack/react-query";

import { reportsApi, type Report } from "@/services/api";
import { Badge, EmptyState, LoadingState } from "@/components/ui";

interface RecentReportsPanelProps {
  selectedZone: string | null;
}

export const RecentReportsPanel: React.FC<RecentReportsPanelProps> = ({
  selectedZone,
}) => {
  const { data: reports = [], isLoading, isError } = useQuery<Report[]>({
    queryKey: ["reports", selectedZone],
    queryFn: async () => {
      const res = await reportsApi.list({
        ...(selectedZone ? { zone_id: selectedZone } : {}),
        limit: 20,
      });
      return res.data.reports || [];
    },
    refetchInterval: 30000,
  });

  return (
    <div className="ops-panel">
      <div className="ops-panel-header">
        <div>
          <div className="ops-kicker">Intake</div>
          <div className="ops-title-sm">Recent reports</div>
        </div>
        <Badge tone="blue">{reports.length}</Badge>
      </div>
      <div className="ops-scroll-y" style={{ maxHeight: 260 }}>
        {isLoading ? (
          <LoadingState label="Loading reports…" />
        ) : isError ? (
          <EmptyState title="Unavailable" message="Could not load reports." />
        ) : reports.length === 0 ? (
          <EmptyState title="No reports" message="No field reports received yet." />
        ) : (
          reports.map((r) => {
            const key = r.report_id ?? r.id ?? `${r.created_at ?? ""}`;
            const preview =
              r.summary || r.message_text || r.transcript || r.excerpt || "";
            const trust = r.trust_score;
            const trustTone =
              trust == null ? "slate" : trust >= 0.7 ? "cyan" : trust >= 0.4 ? "amber" : "red";
            return (
              <div key={key} className="ops-list-item">
                <span className="min-w-0 flex-1">
                  <span className="ops-clamp-2 block text-xs font-medium text-slate-200" title={preview}>
                    {preview.substring(0, 90) || "(empty report)"}
                  </span>
                  <span className="ops-mono mt-1 block text-[11px] text-slate-500">
                    {r.source || "unknown"} · {r.disaster_type || "unknown"}
                    {r.suppressed ? " · suppressed" : ""}
                  </span>
                </span>
                {trust != null && (
                  <Badge tone={trustTone} title={`Trust ${trust.toFixed(2)}`}>
                    {trust.toFixed(2)}
                  </Badge>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
