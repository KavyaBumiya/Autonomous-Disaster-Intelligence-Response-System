import React from "react";
import type { ServiceStatus } from "@/utils/healthStatus";

const DOT: Record<ServiceStatus, string> = {
  ONLINE: "bg-[#38d9c4] shadow-[0_0_8px_#38d9c4]",
  DEGRADED: "bg-[#f3b562] shadow-[0_0_8px_#f3b562]",
  OFFLINE: "bg-[#ff6b6b] shadow-[0_0_8px_#ff6b6b] animate-pulse",
  UNKNOWN: "bg-slate-400 animate-pulse",
};

export const StatusDot: React.FC<{ status: ServiceStatus }> = ({ status }) => (
  <span
    className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[status]}`}
    aria-hidden="true"
  />
);
