import React from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";

interface RecentReportsPanelProps {
  selectedZone: string | null;
}

interface Report {
  report_id: string;
  message_text?: string;
  transcript?: string;
  source?: string;
  disaster_type?: string;
}

export const RecentReportsPanel: React.FC<RecentReportsPanelProps> = ({
  selectedZone,
}) => {
  const { data: reports = [], isLoading } = useQuery<Report[]>({
    queryKey: ["reports", selectedZone],
    queryFn: async () => {
      const url = selectedZone
        ? `/api/reports?zone_id=${selectedZone}`
        : "/api/reports";
      const res = await axios.get(url);
      return res.data.reports || [];
    },
    enabled: !!selectedZone,
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
            const preview = r.message_text || r.transcript || "";
            return (
              <div key={r.report_id} className="p-2 bg-gray-700/50 rounded">
                <div className="font-medium text-white truncate" title={preview}>
                  {preview.substring(0, 50)}
                </div>
                <div className="text-xs">
                  {r.source || "unknown"} • {r.disaster_type || "unknown"}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};