import React from "react";
import { overallLabel, type ServiceStatus } from "@/utils/healthStatus";
import { StatusDot } from "./StatusDot";

const TEXT: Record<ServiceStatus, string> = {
  ONLINE: "text-[#38d9c4]",
  DEGRADED: "text-[#f3b562]",
  OFFLINE: "text-[#ff6b6b]",
  UNKNOWN: "text-slate-400",
};

const BORDER: Record<ServiceStatus, string> = {
  ONLINE: "border-[#38d9c4]/30 bg-[#38d9c4]/10",
  DEGRADED: "border-[#f3b562]/30 bg-[#f3b562]/10",
  OFFLINE: "border-[#ff6b6b]/30 bg-[#ff6b6b]/10",
  UNKNOWN: "border-white/15 bg-white/5",
};

export interface SystemStatusBadgeProps {
  overall: ServiceStatus;
  reasons: string[];
  compact?: boolean;
  onClick?: () => void;
  expanded?: boolean;
}

export const SystemStatusBadge: React.FC<SystemStatusBadgeProps> = ({
  overall,
  reasons,
  compact = false,
  onClick,
  expanded = false,
}) => {
  const label = overallLabel(overall);
  const title = reasons[0] || "";
  const sizeClass = compact ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-xs";
  const className = `inline-flex items-center gap-1.5 rounded-full border font-medium transition hover:opacity-80 ${sizeClass} ${BORDER[overall]} ${TEXT[overall]}`;
  const aria = `System status: ${label.toLowerCase()}`;

  if (!onClick) {
    return (
      <span className={className} title={title} aria-label={aria}>
        <StatusDot status={overall} />
        {label}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={className}
      aria-label={aria}
      aria-expanded={expanded}
      title={title}
    >
      <StatusDot status={overall} />
      {label}
    </button>
  );
};
