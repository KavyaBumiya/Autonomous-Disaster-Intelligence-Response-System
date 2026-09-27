import React from "react";
import {
  SERVICE_LABELS,
  overallLabel,
  serviceLabel,
  type ServiceKey,
  type ServiceStatus,
  type SystemHealth,
} from "@/utils/healthStatus";
import { StatusDot } from "./StatusDot";

const ROW_KEYS: ServiceKey[] = [
  "api",
  "auth",
  "ai",
  "predictions",
  "maps",
  "realtime",
  "weather",
  "seismic",
];

function statusTextClass(status: ServiceStatus): string {
  if (status === "ONLINE") return "text-[#38d9c4]";
  if (status === "DEGRADED" || status === "REQUIRED") return "text-[#f3b562]";
  if (status === "OFFLINE") return "text-[#ff6b6b]";
  return "text-slate-400";
}

function formatTime(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "—";
  }
}

export interface SystemStatusPopoverProps {
  health: SystemHealth;
  onClose: () => void;
  onRefresh: () => void;
}

export const SystemStatusPopover: React.FC<SystemStatusPopoverProps> = ({
  health,
  onClose,
  onRefresh,
}) => {
  const overallLabelText = overallLabel(health.overall);
  const reasonText =
    health.reasons.join(" ") ||
    (health.overall === "ONLINE"
      ? "All core services operational."
      : health.overall === "OFFLINE"
        ? "AegisAI backend is unreachable."
        : health.overall === "DEGRADED"
          ? "Some services are unavailable."
          : "Checking AegisAI services...");

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} aria-hidden="true" />
      <div
        className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-xl border border-white/10 bg-[#0d1b2a] shadow-2xl"
        role="dialog"
        aria-label="System status detail"
      >
        <div className="border-b border-white/10 px-4 py-3">
          <div className="ops-kicker mb-1">System status</div>
          <div className="flex items-center gap-2 text-sm font-semibold">
            <StatusDot status={health.overall} />
            {overallLabelText}
          </div>
        </div>

        <div className="p-2">
          {ROW_KEYS.map((key) => {
            const status = health[key] as ServiceStatus;
            return (
              <div
                key={key}
                className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 transition hover:bg-white/[.04]"
              >
                <span className="text-xs font-medium text-slate-200">
                  {SERVICE_LABELS[key]}
                </span>
                <span
                  className={`inline-flex items-center gap-1.5 text-xs ${statusTextClass(status)}`}
                >
                  <StatusDot status={status} />
                  {serviceLabel(key, status)}
                </span>
              </div>
            );
          })}
          {health.database !== "UNKNOWN" && (
            <div className="flex items-center justify-between gap-3 rounded-lg px-3 py-2">
              <span className="text-xs font-medium text-slate-200">
                {SERVICE_LABELS.database}
              </span>
              <span className="inline-flex items-center gap-1.5 text-xs">
                <StatusDot status={health.database} />
                {overallLabel(health.database)}
              </span>
            </div>
          )}
        </div>

        <div className="border-t border-white/10 px-4 py-3 text-xs leading-5">
          <div className="text-slate-400">
            Last checked:{" "}
            <span className="ops-mono text-slate-300">{formatTime(health.lastChecked)}</span>
          </div>
          <div className="mt-1 flex items-start gap-2">
            <StatusDot status={health.overall} />
            <span>
              <strong>Overall:</strong> {overallLabelText}
            </span>
          </div>
          <p className="mt-2 text-slate-400">
            <strong>Reason:</strong> {reasonText}
          </p>
          {health.ai === "ONLINE" && health.aiModel && (
            <p className="ops-mono mt-1 text-[10px] text-slate-500">
              Model: {health.aiModel}
            </p>
          )}
        </div>

        <div className="flex gap-2 border-t border-white/10 px-4 py-3">
          <button type="button" className="ops-button ops-button-sm flex-1" onClick={onRefresh}>
            Re-check
          </button>
          <button type="button" className="ops-button ops-button-sm" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="border-t border-white/10 px-4 py-2 text-[10px] text-slate-500">
          Decision Engine is local and deterministic. NVIDIA AI is advisory only.
        </div>
      </div>
    </>
  );
};
