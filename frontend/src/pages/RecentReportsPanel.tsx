import React from "react";
import { useQuery } from "@tanstack/react-query";

import { reportsApi, type Report } from "@/services/api";

interface RecentReportsPanelProps {
  selectedZone: string | null;
}

export const RecentReportsPanel: React.FC<RecentReportsPanelProps> = ({
  selectedZone,
}) => {
  const { data: reports = [], isLoading } = useQuery<Report[]>({
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
    <div className="p-4 bg-gray-800/50 rounded-lg h-fit">
      <h3 className="font-medium text-white mb-3">Recent Reports</h3>
      {isLoading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : reports.length === 0 ? (
        <p className="text-sm text-gray-400">No reports yet</p>
      ) : (
        <div className="space-y-2 text-xs text-gray-300">
          {reports.map((r) => {
            const key = r.report_id ?? r.id ?? `${r.created_at ?? ""}`;
            const preview =
              r.summary || r.message_text || r.transcript || r.excerpt || "";
            return (
              <div key={key} className="p-2 bg-gray-700/50 rounded">
                <div className="font-medium text-white truncate" title={preview}>
                  {preview.substring(0, 50) || "(empty report)"}
                </div>
                <div className="text-xs">
                  {r.source || "unknown"} • {r.disaster_type || "unknown"}
                  {r.trust_score != null && ` • trust ${r.trust_score.toFixed(2)}`}
                  {r.suppressed && " • suppressed"}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
