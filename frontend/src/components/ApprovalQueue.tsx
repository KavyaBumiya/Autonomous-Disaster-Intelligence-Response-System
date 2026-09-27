/**
 * AEGIS-AI — Human Approval Gate
 * ================================
 * PRD §9: All safety-critical actions require explicit commander approval.
 * The AI (NVIDIA) cannot approve, reject, or bypass this component.
 *
 * Displays pending actions with full XAI evidence so the commander
 * can make an informed decision before any dispatch occurs.
 */
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { incidentsApi, type Action } from "@/services/api";

// ── Priority colours ──────────────────────────────────────────────────────

const BAND_STYLES: Record<string, { border: string; bg: string; text: string; badge: string }> = {
  CRITICAL: {
    border: "border-[#ff6b6b]/40",
    bg:     "bg-[#ff6b6b]/5",
    text:   "text-[#ff8b8b]",
    badge:  "bg-[#ff6b6b]/20 text-[#ff8b8b]",
  },
  HIGH: {
    border: "border-[#f3b562]/40",
    bg:     "bg-[#f3b562]/5",
    text:   "text-[#f3b562]",
    badge:  "bg-[#f3b562]/20 text-[#f3b562]",
  },
  MEDIUM: {
    border: "border-yellow-500/30",
    bg:     "bg-yellow-500/5",
    text:   "text-yellow-300",
    badge:  "bg-yellow-500/20 text-yellow-300",
  },
  LOW: {
    border: "border-white/10",
    bg:     "bg-white/[.02]",
    text:   "text-slate-400",
    badge:  "bg-white/10 text-slate-400",
  },
};

function getBandStyle(band: string) {
  return BAND_STYLES[band] ?? BAND_STYLES.LOW;
}

// ── Props ─────────────────────────────────────────────────────────────────

interface ApprovalQueueProps {
  actions:   Action[];
  onApprove: (id: string) => void;
  onReject:  (id: string) => void;
  loading:   boolean;
  onRefresh: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────

export const ApprovalQueue: React.FC<ApprovalQueueProps> = ({
  actions,
  onApprove,
  onReject,
  loading,
  onRefresh,
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (actions.length === 0) {
    return (
      <div className="ops-panel p-8 text-center">
        <div className="mb-2 text-4xl">✅</div>
        <div className="ops-title mb-2">No pending approvals</div>
        <p className="text-sm text-slate-400">
          All AI recommendations have been reviewed. The system will notify you
          when new high-priority actions require commander authorisation.
        </p>
        <button onClick={onRefresh} className="ops-button mt-4 rounded-lg px-4 py-2 text-sm">
          Refresh queue
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <div className="ops-kicker mb-1">PRD §9 — Human approval gate</div>
          <h2 className="text-xl font-bold">
            {actions.length} action{actions.length !== 1 ? "s" : ""} awaiting commander review
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            The AI surfaces recommendations with full evidence. You decide.
          </p>
        </div>
        <button onClick={onRefresh} className="ops-button rounded-lg px-3 py-2 text-sm">
          ↻ Refresh
        </button>
      </div>

      {/* Architecture reminder */}
      <div className="mb-5 flex items-start gap-3 rounded-xl border border-[#38d9c4]/20 bg-[#38d9c4]/5 px-4 py-3 text-xs leading-5 text-[#38d9c4]">
        <span className="text-base">🛡️</span>
        <span>
          <strong>Safety constraint:</strong> The AI (NVIDIA) cannot approve, reject, or bypass
          this queue. Every approval creates an immutable audit record with your user ID,
          role, and timestamp.
        </span>
      </div>

      {/* Action cards */}
      <div className="space-y-4">
        {actions.map((action) => (
          <ActionCard
            key={action.action_id}
            action={action}
            expanded={expandedId === action.action_id}
            onToggleExpand={() =>
              setExpandedId((id) => (id === action.action_id ? null : action.action_id))
            }
            onApprove={() => onApprove(action.action_id)}
            onReject={()  => onReject(action.action_id)}
            loading={loading}
          />
        ))}
      </div>
    </div>
  );
};

// ── Action card ───────────────────────────────────────────────────────────

interface ActionCardProps {
  action:         Action;
  expanded:       boolean;
  onToggleExpand: () => void;
  onApprove:      () => void;
  onReject:       () => void;
  loading:        boolean;
}

const ActionCard: React.FC<ActionCardProps> = ({
  action,
  expanded,
  onToggleExpand,
  onApprove,
  onReject,
  loading,
}) => {
  const style = getBandStyle(action.priority_band);

  // Fetch incident detail when expanded
  const { data: incident } = useQuery({
    queryKey: ["incident", action.incident_id],
    queryFn:  () => incidentsApi.get(action.incident_id).then((r) => r.data),
    enabled:  expanded,
    staleTime: 30_000,
  });

  return (
    <div className={`overflow-hidden rounded-xl border ${style.border} ${style.bg}`}>
      {/* Card header */}
      <div className="flex items-start gap-4 p-4">
        {/* Priority badge */}
        <div className={`shrink-0 rounded-lg px-2 py-1 text-xs font-bold uppercase ${style.badge}`}>
          {action.priority_band}
        </div>

        {/* Info */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className={`text-base font-semibold ${style.text}`}>
              Priority {action.priority_score.toFixed(0)}/100
            </span>
            <span className="text-xs text-slate-500">·</span>
            <span className="text-xs text-slate-400 uppercase">{action.action_type}</span>
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-slate-300">{action.description}</p>
          <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>Recommended by: {action.recommended_by}</span>
            <span>·</span>
            <span>Zone: {action.zone_id?.slice(0, 8)}</span>
            <span>·</span>
            <span>{action.created_at ? new Date(action.created_at).toLocaleString() : "—"}</span>
          </div>
        </div>

        {/* Approve / Reject */}
        <div className="flex shrink-0 flex-col gap-2">
          <button
            onClick={onApprove}
            disabled={loading}
            className="rounded-lg bg-[#38d9c4]/20 px-5 py-2 text-sm font-semibold text-[#38d9c4] transition hover:bg-[#38d9c4]/30 disabled:opacity-40"
          >
            ✓ Approve
          </button>
          <button
            onClick={onReject}
            disabled={loading}
            className="rounded-lg bg-[#ff6b6b]/20 px-5 py-2 text-sm font-semibold text-[#ff6b6b] transition hover:bg-[#ff6b6b]/30 disabled:opacity-40"
          >
            ✗ Reject
          </button>
        </div>
      </div>

      {/* Expand toggle */}
      <button
        onClick={onToggleExpand}
        className="w-full border-t border-white/10 px-4 py-2 text-left text-xs text-slate-400 transition hover:text-white"
      >
        {expanded ? "▲ Hide evidence" : "▼ Show XAI evidence & incident details"}
      </button>

      {/* Expanded evidence */}
      {expanded && (
        <div className="border-t border-white/10 p-4">
          {incident ? (
            <div className="space-y-4">
              {/* Key metrics */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Victims",       value: incident.victim_count ?? 0 },
                  { label: "Reports",       value: incident.report_count ?? 0 },
                  { label: "Avg trust",     value: `${((incident.avg_trust_score ?? 0) * 100).toFixed(0)}%` },
                  { label: "Disaster type", value: incident.disaster_type ?? "unknown" },
                ].map((m) => (
                  <div key={m.label} className="rounded-lg border border-white/10 bg-white/[.03] p-3">
                    <div className="ops-kicker">{m.label}</div>
                    <div className="mt-1 text-lg font-bold">{m.value}</div>
                  </div>
                ))}
              </div>

              {/* XAI reasoning */}
              {incident.xai_reasoning && (
                <div>
                  <div className="ops-kicker mb-2">XAI Factor Breakdown</div>
                  <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-xs leading-5 text-slate-300">
                    {incident.xai_reasoning}
                  </pre>
                </div>
              )}

              {/* NVIDIA explanation */}
              {incident.groq_explanation && (
                <div>
                  <div className="ops-kicker mb-2">AI Explanation (NVIDIA)</div>
                  <p className="rounded-lg border border-[#38d9c4]/20 bg-[#38d9c4]/5 p-3 text-sm leading-6 text-slate-200">
                    {incident.groq_explanation}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-500">Loading incident details…</p>
          )}
        </div>
      )}
    </div>
  );
};
