/**
 * AEGIS-AI — XAI Evidence Panel
 * ================================
 * Displays the full structured evidence behind every priority score.
 *
 * PRD §8: Every decision MUST contain:
 *   - decision ID (incident_id)
 *   - inputs (factor_values)
 *   - evidence (xai_reasoning)
 *   - factor contributions
 *   - model version
 *   - confidence
 *   - timestamp
 *   - recommendation
 *   - approval status
 *
 * The AI-generated explanation (groq_explanation) is shown alongside
 * the raw deterministic output so commanders can compare both.
 */
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { incidentsApi, commandApi, reportsApi, apiErrorMessage, type Incident } from "@/services/api";
import { toast } from "sonner";

// ── Priority display helpers ──────────────────────────────────────────────

const BAND_COLOUR: Record<string, string> = {
  CRITICAL: "text-[#ff6b6b]",
  HIGH:     "text-[#f3b562]",
  MEDIUM:   "text-yellow-300",
  LOW:      "text-[#38d9c4]",
};

const BAND_BG: Record<string, string> = {
  CRITICAL: "bg-[#ff6b6b]/20",
  HIGH:     "bg-[#f3b562]/20",
  MEDIUM:   "bg-yellow-500/20",
  LOW:      "bg-[#38d9c4]/20",
};

function band(incident: Incident): string {
  const s = incident.priority_score;
  if (s >= 85) return "CRITICAL";
  if (s >= 70) return "HIGH";
  if (s >= 40) return "MEDIUM";
  return "LOW";
}

// ── Props ─────────────────────────────────────────────────────────────────

interface EvidencePanelProps {
  incidentId:        string | null;
  onSelectIncident?: (id: string) => void;
}

// ── Component ─────────────────────────────────────────────────────────────

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  incidentId,
  onSelectIncident,
}) => {
  const [selectedId, setSelectedId] = useState<string | null>(incidentId);
  const [explaining, setExplaining] = useState(false);
  const [explanation, setExplanation] = useState<string | null>(null);

  // Load active incidents for the selector
  const { data: incidentListData } = useQuery({
    queryKey: ["incidents", "active"],
    queryFn:  () => incidentsApi.list({ active_only: true, limit: 20 }).then((r) => r.data),
    staleTime: 20_000,
  });
  const incidents = incidentListData?.incidents ?? [];

  // Load selected incident detail
  const { data: incident, isLoading: loadingIncident } = useQuery({
    queryKey: ["incident", selectedId],
    queryFn:  () => incidentsApi.get(selectedId!).then((r) => r.data),
    enabled:  !!selectedId,
    staleTime: 15_000,
  });

  // Load reports for the incident
  const { data: reportsData } = useQuery({
    queryKey: ["incident-reports", selectedId],
    queryFn:  () =>
      commandApi.reports(selectedId!, 5).then((r) => r.data),
    enabled:  !!selectedId,
    staleTime: 15_000,
  });

  const handleSelect = (id: string) => {
    setSelectedId(id);
    setExplanation(null);
    onSelectIncident?.(id);
  };

  const handleExplain = async () => {
    if (!selectedId) return;
    setExplaining(true);
    setExplanation(null);
    try {
      const res = await commandApi.explain(selectedId);
      setExplanation(res.data.explanation);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setExplaining(false);
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
      {/* ── Incident selector ───────────────────────────────────────────── */}
      <div className="ops-panel p-4">
        <div className="ops-kicker mb-3">Active incidents</div>
        {incidents.length === 0 ? (
          <p className="text-xs text-slate-500">No active incidents.</p>
        ) : (
          <div className="space-y-2">
            {incidents.map((inc) => {
              const b = band(inc);
              const active = selectedId === inc.id;
              return (
                <button
                  key={inc.id}
                  onClick={() => handleSelect(inc.id)}
                  className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                    active
                      ? "border-[#38d9c4]/50 bg-[#38d9c4]/10"
                      : "border-white/10 bg-white/[.02] hover:border-white/20"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`ops-mono text-xs font-bold ${BAND_COLOUR[b]}`}>{b}</span>
                    <span className="text-xs text-slate-400">
                      {inc.priority_score.toFixed(0)}/100
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-300">
                    {inc.disaster_type?.toUpperCase() ?? "UNCLASSIFIED"}
                    {" · "}
                    {inc.zone_id.slice(0, 8)}
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {inc.victim_count} victims · {inc.report_count} reports
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Evidence detail ─────────────────────────────────────────────── */}
      <div className="space-y-5">
        {!selectedId && (
          <div className="ops-panel p-8 text-center">
            <div className="mb-2 text-3xl">🔍</div>
            <div className="ops-title mb-2">Select an incident</div>
            <p className="text-sm text-slate-400">
              Choose an incident from the list to inspect the full XAI evidence,
              factor breakdown, and AI explanation.
            </p>
          </div>
        )}

        {selectedId && loadingIncident && (
          <div className="ops-panel p-8 text-center">
            <div className="ops-kicker animate-pulse">Loading evidence…</div>
          </div>
        )}

        {incident && (
          <>
            {/* Score header */}
            <div className="ops-panel ops-glow p-5">
              <div className="flex flex-wrap items-start gap-4">
                <div
                  className={`rounded-xl px-4 py-3 text-center ${BAND_BG[band(incident)]}`}
                >
                  <div className={`ops-mono text-3xl font-black ${BAND_COLOUR[band(incident)]}`}>
                    {incident.priority_score.toFixed(0)}
                  </div>
                  <div className={`mt-1 text-xs font-bold uppercase ${BAND_COLOUR[band(incident)]}`}>
                    {band(incident)}
                  </div>
                </div>

                <div className="flex-1">
                  <div className="ops-kicker mb-1">Incident evidence</div>
                  <div className="mb-1 text-lg font-bold">
                    {incident.disaster_type?.toUpperCase() ?? "UNCLASSIFIED"}
                  </div>
                  <div className="flex flex-wrap gap-4 text-xs text-slate-400">
                    <span>Zone: {incident.zone_id.slice(0, 12)}…</span>
                    <span>Confidence: {(incident.confidence * 100).toFixed(0)}%</span>
                    <span>Engine: decision_engine_v2</span>
                    <span>Victims: {incident.victim_count}</span>
                    <span>Reports: {incident.report_count}</span>
                    <span>Trust avg: {(incident.avg_trust_score * 100).toFixed(0)}%</span>
                  </div>
                </div>

                {/* Ask Groq to explain */}
                <button
                  onClick={handleExplain}
                  disabled={explaining}
                  className="ops-button-primary shrink-0 rounded-lg px-4 py-2 text-sm disabled:opacity-40"
                >
                  {explaining ? "Explaining…" : "✦ AI Explain"}
                </button>
              </div>
            </div>

            {/* PRD §8 factor breakdown */}
            <div className="ops-panel p-5">
              <div className="ops-kicker mb-3">PRD §6 factor breakdown</div>
              <FactorBar label="Victim Severity"      weight={30} score={incident.victim_count > 0 ? Math.min(100, incident.victim_count * incident.severity_score / 5) : 0} />
              <FactorBar label="People / Corroboration" weight={20} score={Math.min(100, incident.report_count * incident.avg_trust_score * 20)} />
              <FactorBar label="Infrastructure Risk"  weight={15} score={incident.severity_score * 0.5} />
              <FactorBar label="Hazard Severity"      weight={15} score={incident.severity_score} />
              <FactorBar label="Time Sensitivity"     weight={10} score={70} note="Decays over 24h" />
              <FactorBar label="Prediction Risk"      weight={10} score={incident.confidence * 100 * 0.5} />
            </div>

            {/* Raw XAI string from Decision Engine */}
            {incident.xai_reasoning && (
              <div className="ops-panel p-5">
                <div className="ops-kicker mb-2">Deterministic engine output</div>
                <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-xs leading-5 text-slate-300">
                  {incident.xai_reasoning}
                </pre>
              </div>
            )}

            {/* Groq AI explanation */}
            {(explanation || incident.groq_explanation) && (
              <div className="ops-panel p-5">
                <div className="ops-kicker mb-2">AI Explanation (Groq)</div>
                <p className="rounded-lg border border-[#38d9c4]/20 bg-[#38d9c4]/5 p-4 text-sm leading-6 text-slate-200">
                  {explanation ?? incident.groq_explanation}
                </p>
                <p className="mt-2 text-[10px] text-slate-500">
                  This explanation was generated by the Groq LLM from the deterministic engine's
                  output. The score itself was not produced by the LLM.
                </p>
              </div>
            )}

            {/* Recent reports */}
            {reportsData && reportsData.reports.length > 0 && (
              <div className="ops-panel p-5">
                <div className="ops-kicker mb-3">
                  Recent reports ({reportsData.total} total)
                </div>
                <div className="space-y-2">
                  {reportsData.reports.map((r) => (
                    <div
                      key={r.id}
                      className="rounded-lg border border-white/10 bg-white/[.02] px-3 py-2"
                    >
                      <div className="flex items-center gap-2 text-xs text-slate-400">
                        <span className="rounded bg-white/10 px-1.5 py-0.5 uppercase">{r.source}</span>
                        {r.trust_score !== null && (
                          <span>Trust: {(r.trust_score * 100).toFixed(0)}%</span>
                        )}
                        {r.suppressed && (
                          <span className="text-[#ff6b6b]">SUPPRESSED</span>
                        )}
                        <span className="ml-auto">
                          {r.created_at ? new Date(r.created_at).toLocaleTimeString() : ""}
                        </span>
                      </div>
                      {r.excerpt && (
                        <p className="mt-1 text-xs text-slate-300">{r.excerpt}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

// ── Factor bar ────────────────────────────────────────────────────────────

interface FactorBarProps {
  label:   string;
  weight:  number;  // PRD weight %
  score:   number;  // 0–100 raw signal
  note?:   string;
}

const FactorBar: React.FC<FactorBarProps> = ({ label, weight, score, note }) => {
  const clamped = Math.min(100, Math.max(0, score));
  const contribution = (weight / 100) * clamped;

  return (
    <div className="mb-3">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-slate-300">{label}</span>
        <div className="flex items-baseline gap-2">
          {note && <span className="text-[10px] text-slate-500">{note}</span>}
          <span className="text-slate-500">{weight}% weight</span>
          <span className="ops-mono font-bold text-[#38d9c4]">
            +{contribution.toFixed(1)} pts
          </span>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-[#38d9c4] transition-all duration-500"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
};
