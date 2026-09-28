import { useMemo } from "react";
import { api } from "./api";
import { useApiResource } from "./hooks";
import type { Incident } from "./types";

export interface DashboardAIBrief {
  activeEmergency: boolean;
  title: string;
  summary: string;
  preparations: string[];
  raw: string;
}

const EMPTY_BRIEF: DashboardAIBrief = {
  activeEmergency: false,
  title: "No Emergency Yet",
  summary: "AegisAI has not identified an active emergency for the selected zone.",
  preparations: [],
  raw: "",
};

function parseBrief(raw: string): DashboardAIBrief {
  const text = raw.trim();
  if (!text) return EMPTY_BRIEF;

  const alertMatch = text.match(/ALERT\s*:\s*(YES|NO)/i);
  const activeEmergency = alertMatch
    ? alertMatch[1].toUpperCase() === "YES"
    : /active emergency|immediate response|evacuat|critical incident|flooding is active/i.test(text);

  const prepBlock = text.match(/PREPARATIONS?\s*:\s*([\s\S]*)/i)?.[1] ?? "";
  const preparations = prepBlock
    .split(/\n|\s*\d+[.)]\s*|\s*[-•]\s*/)
    .map((item) => item.replace(/^[:\-•\s]+/, "").trim())
    .filter(Boolean)
    .slice(0, 4);

  const summary = (text.match(/SUMMARY\s*:\s*(.*)/i)?.[1] ?? text)
    .replace(/^ALERT\s*:\s*(YES|NO)\s*/i, "")
    .trim();

  return {
    activeEmergency,
    title: activeEmergency ? "AI-prioritized emergency" : "No Emergency Yet",
    summary: activeEmergency ? summary : "AegisAI has not identified an active emergency for the selected zone.",
    preparations: activeEmergency ? preparations : [],
    raw: text,
  };
}

export function useDashboardAI(
  zoneId: string | null,
  incident: Incident | null,
  enabled: boolean,
) {
  const key = useMemo(
    () => `dashboard-ai:${zoneId ?? "none"}:${incident?.incident_id ?? "none"}:${incident?.updated_at ?? "none"}`,
    [zoneId, incident?.incident_id, incident?.updated_at],
  );

  return useApiResource<DashboardAIBrief>(
    async (signal) => {
      const context = incident
        ? `Current incident: ${incident.disaster_type ?? "unknown hazard"}; priority ${incident.priority_score}; severity ${incident.severity_score ?? "unknown"}; confidence ${incident.confidence ?? "unknown"}; victims ${incident.victim_count}; reports ${incident.report_count}; status ${incident.status}; location ${incident.lat},${incident.lng}.`
        : "There is currently no active incident record in the selected zone.";

      const result = await api.commandQuery(
        {
          user_query:
            `Assess the current disaster situation for the command dashboard. ${context} ` +
            `Return exactly three labeled parts: ALERT: YES or NO; SUMMARY: one concise sentence; PREPARATIONS: up to 4 concise operator preparation suggestions. ` +
            `Only use live context supplied by the system. If there is no active emergency requiring response, return ALERT: NO and do not invent preparations.`,
          include_xai: true,
          zone_context: zoneId,
        },
        signal,
      );
      return parseBrief(result.response ?? "");
    },
    key,
    { intervalMs: 60_000, enabled: enabled && Boolean(zoneId) },
  );
}

export { EMPTY_BRIEF };
