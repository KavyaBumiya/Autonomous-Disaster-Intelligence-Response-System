import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";

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
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch reports from API
  const { data = [], isLoading } = useQuery<Report[]>({
    queryKey: ["reports", selectedZone],
    queryFn: async () => {
      if (!selectedZone) {
        const res = await axios.get("/api/reports");
        return res.data.reports || [];
      }
      const res = await axios.get(`/api/reports?zone_id=${selectedZone}`);
      return res.data.reports || [];
    },
    enabled: !!selectedZone,
  });

  useEffect(() => {
    if (data && data.length > 0) {
      setReports(data);
      setLoading(false);
    }
  }, [data]);

  useEffect(() => {
    if (loading && data?.length === 0 && !isLoading) {
      toast.info("No recent reports");
      setLoading(false);
    }
  }, [loading, data, isLoading]);

  return (
    <div className="p-4 bg-gray-800/50 rounded-lg h-fit">
      <h3 className="font-medium text-white mb-3">Recent Reports</h3>
      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : reports.length === 0 ? (
        <p className="text-sm text-gray-400">No reports yet</p>
      ) : (
        <div className="space-y-2 text-xs text-gray-300">
          {reports.map((r) => (
            <div key={r.report_id} className="p-2 bg-gray-700/50 rounded">
              <div className="font-medium text-white truncate" title={r.message_text || r.transcript || ""}>
                {(r.message_text || r.transcript || "").substring(0, 50)}
              </div>
              <div className="text-xs">
                {r.source || "unknown"} • {r.disaster_type || "unknown"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};