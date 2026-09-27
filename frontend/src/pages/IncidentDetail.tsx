import React, { Suspense, lazy, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  incidentsApi,
  zonesApi,
  resourcesApi,
  commandApi,
  type Incident,
  type Zone,
} from "@/services/api";
import { AppShell } from "@/components/AppShell";
import { SystemStatus } from "@/components/SystemStatus";
import { WhatIfSimulation } from "@/components/WhatIfSimulation";
import { RouteIntelligence } from "@/components/RouteIntelligence";
import { ResourcePanel } from "@/components/ResourcePanel";
import { EvidencePanel } from "@/components/EvidencePanel";
import { WeatherWidget } from "@/components/WeatherWidget";
import { SeismicPanel } from "@/components/SeismicPanel";
import { useSystemHealth } from "@/hooks/useSystemHealth";
import {
  Badge,
  Button,
  ConfidenceBadge,
  EmptyState,
  LoadingState,
  PriorityBadge,
} from "@/components/ui";

const CesiumGlobe = lazy(() =>
  import("@/components/CesiumGlobe").then((m) => ({ default: m.CesiumGlobe }))
);

type DetailTab = "overview" | "evidence" | "prediction" | "resources" | "route" | "audit";

const TABS: Array<{ id: DetailTab; label: string; hint?: string }> = [
  { id: "overview", label: "Overview" },
  { id: "evidence", label: "Evidence" },
  { id: "prediction", label: "Prediction" },
  { id: "resources", label: "Resources" },
  { id: "route", label: "Route" },
  { id: "audit", label: "Audit" },
];

const MapFallback = () => (
  <div className="ops-map flex items-center justify-center" style={{ height: "clamp(280px, 36vh, 420px)" }}>
    <div className="text-center">
      <div className="ops-kicker mb-2">Live map</div>
      <div className="ops-title">Loading map engine…</div>
    </div>
  </div>
);

interface OverviewRow {
  label: string;
  value: React.ReactNode;
}

export const IncidentDetail: React.FC = () => {
  const { incidentId } = useParams<{ incidentId: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<DetailTab>("overview");
  const { ai: aiStatus } = useSystemHealth();
  const aiUnavailable = aiStatus === "OFFLINE" || aiStatus === "DEGRADED";

  const { data: incident, isLoading, isError } = useQuery<Incident>({
    queryKey: ["incident", incidentId],
    queryFn: async () => {
      const res = await incidentsApi.get(incidentId!);
      return res.data;
    },
    enabled: !!incidentId,
    refetchInterval: 20000,
  });

  const zoneId = incident?.zone_id ?? null;

  const { data: zoneResponse } = useQuery<{ zones: Zone[] }>({
    queryKey: ["zones"],
    queryFn: async () => (await zonesApi.withPriority()).data,
    refetchInterval: 30000,
  });
  const zones = zoneResponse?.zones ?? [];
  const zone = zones.find((z) => z.zone_id === zoneId) ?? null;

  const { data: resourcesData } = useQuery({
    queryKey: ["resources", "for-incident", zoneId],
    queryFn: async () => (await resourcesApi.list(zoneId ? { zone_id: zoneId } : {})).data,
    enabled: Boolean(zoneId),
    refetchInterval: 20000,
  });
  const resources = resourcesData?.resources ?? [];
  const readyResources = resources.filter(
    (r) => r.available && (r.current_load ?? 0) < (r.capacity ?? 0),
  );

  const { data: queueData } = useQuery({
    queryKey: ["approval-queue"],
    queryFn: async () => (await commandApi.approvalQueue()).data,
    refetchInterval: 15000,
  });
  const pendingForIncident = (queueData?.actions ?? []).filter(
    (a) => a.incident_id === incidentId,
  );
  const needsApproval = pendingForIncident.length > 0;

  const { data: auditReports } = useQuery({
    queryKey: ["incident-reports", incidentId],
    queryFn: async () => (await commandApi.reports(incidentId!, 20)).data,
    enabled: !!incidentId,
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <AppShell>
        <LoadingState label="Loading incident…" />
      </AppShell>
    );
  }

  if (isError || !incident) {
    return (
      <AppShell>
        <div className="ops-panel p-6">
          <div className="ops-title mb-2">Incident unavailable</div>
          <p className="text-sm text-slate-400">
            Could not load incident {incidentId}. It may have been resolved or the backend is offline.
          </p>
          <Button className="mt-4" onClick={() => navigate("/dashboard")}>
            Back to dashboard
          </Button>
        </div>
      </AppShell>
    );
  }

  const disaster = (incident.disaster_type || "Incident").toUpperCase();
  const zoneLabel =
    zone?.name ||
    (zoneId ? `ZONE ${zoneId.slice(0, 8).toUpperCase()}` : "UNASSIGNED ZONE");
  const statusLabel = incident.active
    ? (incident.status || "ACTIVE").toUpperCase()
    : (incident.status || "CLOSED").toUpperCase();
  const confidencePct = Math.round((incident.confidence || 0) * 100);
  const priority = Math.round(incident.priority_score || 0);

  const overviewRows: OverviewRow[] = [
    {
      label: "Location",
      value: zone
        ? `${zone.name || zone.zone_id.slice(0, 8)} · ${zone.centroid_lat.toFixed(4)}, ${zone.centroid_lng.toFixed(4)}`
        : incident.lat != null && incident.lng != null
          ? `${incident.lat.toFixed(4)}, ${incident.lng.toFixed(4)}`
          : zoneId || "—",
    },
    { label: "Disaster type", value: incident.disaster_type || "Unknown" },
    {
      label: "Priority",
      value: (
        <span className="flex items-center gap-2">
          <PriorityBadge score={incident.priority_score} band={incident.priority_band} />
          <span className="ops-mono text-xs text-slate-400">{priority}/100</span>
        </span>
      ),
    },
    {
      label: "Victims",
      value: (
        <span>
          <strong className="text-white">{incident.victim_count || 0}</strong>
          <span className="ops-mono ml-2 text-xs text-slate-400">
            conf {Math.round((incident.victim_confidence || 0) * 100)}%
          </span>
        </span>
      ),
    },
    { label: "Status", value: statusLabel },
    {
      label: "Reports / trust",
      value: (
        <span>
          {incident.report_count || 0} reports ·{" "}
          {Math.round((incident.avg_trust_score || 0) * 100)}% avg trust
        </span>
      ),
    },
    {
      label: "Radius",
      value: zone ? `${Math.round(zone.radius_meters / 100) / 10} km` : "—",
    },
    {
      label: "Opened",
      value: incident.created_at
        ? new Date(incident.created_at).toLocaleString()
        : "—",
    },
  ];

  return (
    <AppShell alertCount={pendingForIncident.length}>
      {/* ── Header strip: Back | Incident | Status | Alerts | Command ── */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => window.history.length > 1 ? window.history.back() : navigate("/dashboard")}>
            ← Back
          </Button>
          <Link to="/dashboard" className="ops-button ops-button-sm">
            Dashboard
          </Link>
          <span className="ops-mono text-xs text-slate-500">
            /incidents/{incidentId?.slice(0, 12)}
            {incidentId && incidentId.length > 12 ? "…" : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SystemStatus compact />
          <Link to="/alerts" className="ops-button ops-button-sm">
            Alerts
            {needsApproval && (
              <span className="grid h-4 min-w-4 place-items-center rounded-full bg-[#ff6b6b] px-1 text-[10px] font-bold text-white">
                {pendingForIncident.length}
              </span>
            )}
          </Link>
          <Link to="/command" className="ops-button ops-button-primary ops-button-sm">
            Command center
          </Link>
        </div>
      </div>

      {/* ── Incident summary bar ─────────────────────────────────────── */}
      <section
        className="ops-panel ops-glow ops-summary-bar mb-5 fade-in"
        aria-label="Incident summary"
      >
        <div className="flex flex-col gap-4 p-4 md:flex-row md:items-center md:justify-between md:gap-6">
          <div className="min-w-0">
            <div className="ops-kicker mb-1">Incident {incident.incident_id.slice(0, 8)}</div>
            <h1 className="truncate text-2xl font-bold tracking-tight md:text-3xl">
              {disaster} <span className="text-slate-500">—</span>{" "}
              <span className="text-[#38d9c4]">{zoneLabel}</span>
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2 md:gap-3">
            <Badge tone={incident.active ? "cyan" : "slate"}>
              <span className="ops-badge-dot" />
              {statusLabel}
            </Badge>
            <PriorityBadge score={incident.priority_score} band={`PRIORITY ${priority}`} />
            <ConfidenceBadge value={incident.confidence} />
            <Badge tone={incident.victim_count ? "red" : "slate"}>
              {incident.victim_count || 0} victims
            </Badge>
            <Badge tone={needsApproval ? "amber" : "blue"}>
              {needsApproval ? "Needs approval" : "AI advisory"}
            </Badge>
            <Badge tone={readyResources.length ? "cyan" : "amber"}>
              {readyResources.length} units ready
            </Badge>
          </div>
        </div>
        {needsApproval && (
          <div className="ops-alert ops-alert-warning border-t border-[var(--line)]">
            <span aria-hidden="true">△</span>
            <span>
              {pendingForIncident.length} action{pendingForIncident.length !== 1 ? "s" : ""} for this
              incident await commander approval — review in Command center.
            </span>
            <Link to="/command" className="ops-button ops-button-sm ml-auto shrink-0">
              Review
            </Link>
          </div>
        )}
      </section>

      {/* ── Weather + seismic context (Phase 15) ───────────────────── */}
      <section className="mb-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        {zone && Number.isFinite(zone.centroid_lat) && Number.isFinite(zone.centroid_lng) && (
          <WeatherWidget
            lat={zone.centroid_lat}
            lng={zone.centroid_lng}
            label={zone.name || "Incident zone"}
          />
        )}
        <SeismicPanel limit={3} />
      </section>

      {/* ── Overview + Live map ──────────────────────────────────────── */}
      <section className="mb-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <div className="ops-panel">
          <div className="ops-panel-header">
            <div>
              <div className="ops-kicker">Incident overview</div>
              <div className="ops-title">Situation snapshot</div>
            </div>
            <span className="ops-mono text-xs text-slate-400">
              {incident.active ? "LIVE" : "HISTORICAL"}
            </span>
          </div>
          <div className="ops-panel-body">
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              {overviewRows.map((row) => (
                <div key={row.label} className="border-b border-[var(--line)] pb-2 last:border-b-0">
                  <dt className="ops-stat-label">{row.label}</dt>
                  <dd className="mt-1 text-sm text-slate-200">{row.value}</dd>
                </div>
              ))}
            </dl>

            <div className="ops-panel-flat mt-4 p-4">
              <div className="ops-kicker mb-2">AI summary &amp; XAI reasoning</div>
              <div
                className="ops-scroll-y space-y-3 text-sm leading-6 text-slate-300"
                style={{ maxHeight: 180 }}
              >
                {incident.groq_summary && (
                  <p className="whitespace-pre-wrap">{incident.groq_summary}</p>
                )}
                {!incident.groq_summary && aiUnavailable && (
                  <div className="rounded-lg border border-[#f3b562]/30 bg-[#f3b562]/10 px-3 py-2 text-xs text-[#f3b562]">
                    AI summary unavailable while NVIDIA is offline. Deterministic XAI evidence and
                    core incident data remain available.
                  </div>
                )}
                <p className="whitespace-pre-wrap text-slate-400">
                  {incident.xai_reasoning || "No reasoning available"}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="ops-panel overflow-hidden">
          <div className="ops-panel-header">
            <div>
              <div className="ops-kicker">3D Globe</div>
              <div className="ops-title">Incident geospatial view</div>
            </div>
            <span className="ops-mono text-xs text-slate-400">
              {zone ? "RISK ZONE" : "NO ZONE"}
            </span>
          </div>
          <Suspense fallback={<MapFallback />}>
            <CesiumGlobe
              zones={zones}
              onSelectZone={(id) => navigate(`/dashboard/${id}`)}
              height="clamp(280px, 36vh, 420px)"
            />
          </Suspense>
          <div className="flex flex-wrap gap-3 border-t border-[var(--line)] px-4 py-3 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-[#ff6b6b]" /> Incident marker
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-[#f3b562]" /> Risk zone
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-[#38d9c4]" /> Resources / safe
            </span>
            <span className="ops-mono ml-auto">
              {incident.lat != null && incident.lng != null
                ? `${incident.lat.toFixed(4)}, ${incident.lng.toFixed(4)}`
                : zone
                  ? `${zone.centroid_lat.toFixed(4)}, ${zone.centroid_lng.toFixed(4)}`
                  : "coords pending"}
            </span>
          </div>
        </div>
      </section>

      {/* ── Tabs ─────────────────────────────────────────────────────── */}
      <div
        className="ops-panel mb-5"
        role="tablist"
        aria-label="Incident operations tabs"
      >
        <div className="flex flex-wrap gap-1 border-b border-[var(--line)] p-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              id={`tab-${tab.id}`}
              onClick={() => setActiveTab(tab.id)}
              className={`ops-nav-link ${activeTab === tab.id ? "active" : ""}`}
            >
              {tab.label}
              {tab.id === "resources" && readyResources.length > 0 && (
                <span className="ops-badge ops-badge-cyan ml-1">{readyResources.length}</span>
              )}
              {tab.id === "audit" && (auditReports?.reports?.length ?? 0) > 0 && (
                <span className="ops-badge ops-badge-blue ml-1">
                  {auditReports?.reports?.length}
                </span>
              )}
            </button>
          ))}
        </div>

        <div
          className="ops-panel-body"
          role="tabpanel"
          id={`panel-${activeTab}`}
          aria-labelledby={`tab-${activeTab}`}
        >
          {activeTab === "overview" && (
            <div className="grid gap-5 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-4">
                <div className="ops-kpi-grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
                  <div className="ops-stat" style={{ minHeight: 96 }}>
                    <div className="ops-stat-label">Priority score</div>
                    <div
                      className="ops-stat-value"
                      style={{
                        color:
                          priority >= 70
                            ? "var(--red)"
                            : priority >= 40
                              ? "var(--amber)"
                              : "var(--cyan)",
                      }}
                    >
                      {priority}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      {incident.priority_band || "—"} band
                    </div>
                  </div>
                  <div className="ops-stat" style={{ minHeight: 96 }}>
                    <div className="ops-stat-label">People at risk</div>
                    <div className="ops-stat-value">{incident.victim_count || 0}</div>
                    <div className="mt-1 text-xs text-slate-400">
                      {confidencePct}% detection conf
                    </div>
                  </div>
                  <div className="ops-stat" style={{ minHeight: 96 }}>
                    <div className="ops-stat-label">Evidence quality</div>
                    <div className="ops-stat-value">
                      {Math.round((incident.avg_trust_score || 0) * 100)}%
                    </div>
                    <div className="ops-progress mt-2">
                      <span
                        style={{ width: `${Math.round((incident.avg_trust_score || 0) * 100)}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="ops-panel-flat p-4">
                  <div className="ops-kicker mb-2">What happened</div>
                  <p className="text-sm leading-6 text-slate-300 whitespace-pre-wrap">
                    {incident.groq_summary ||
                      incident.xai_reasoning ||
                      (aiUnavailable
                        ? "AI narrative unavailable. Deterministic priority, field evidence, and operational tabs remain online."
                        : "No narrative available yet. Evidence builds as field reports arrive.")}
                  </p>
                </div>

                <div className="ops-panel-flat p-4">
                  <div className="ops-kicker mb-2">What is predicted next</div>
                  <p className="text-sm leading-6 text-slate-400">
                    Run a what-if simulation on the <strong>Prediction</strong> tab to project
                    flood/fire escalation under altered rainfall, wind, or resource levels. Current
                    deterministic priority is{" "}
                    <span className="ops-mono text-[#38d9c4]">{priority}/100</span>.
                  </p>
                  <Button
                    size="sm"
                    className="mt-3"
                    onClick={() => setActiveTab("prediction")}
                  >
                    Open prediction tools
                  </Button>
                </div>
              </div>

              <div className="space-y-4">
                <div className="ops-panel-flat p-4">
                  <div className="ops-kicker mb-2">Recommended resources</div>
                  <div className="ops-stat-value text-[#38d9c4]">
                    {readyResources.length}
                    <span className="ops-stat-label ml-2">of {resources.length} ready</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">
                    Units available for assignment to this zone. Allocation runs the backend
                    resource-commander and requires no LLM approval.
                  </p>
                  <Button
                    variant="primary"
                    size="sm"
                    block
                    className="mt-3"
                    onClick={() => setActiveTab("resources")}
                  >
                    Open resource commander
                  </Button>
                </div>

                <div className="ops-panel-flat p-4">
                  <div className="ops-kicker mb-2">Responder route</div>
                  <p className="text-xs leading-5 text-slate-400">
                    Compute primary and alternate corridors with blocked-road constraints for
                    dispatch.
                  </p>
                  <Button size="sm" block className="mt-3" onClick={() => setActiveTab("route")}>
                    Open route intelligence
                  </Button>
                </div>

                <div className="ops-panel-flat p-4">
                  <div className="ops-kicker mb-2">Human approval gate</div>
                  <div className={`ops-badge ${needsApproval ? "ops-badge-amber" : "ops-badge-cyan"} mb-2`}>
                    {needsApproval ? "Action pending" : "No pending actions"}
                  </div>
                  <p className="text-xs leading-5 text-slate-400">
                    {needsApproval
                      ? `${pendingForIncident.length} recommended action(s) for this incident need commander sign-off before dispatch.`
                      : "AI recommendations for this incident are advisory only until an action enters the approval queue."}
                  </p>
                  <Button
                    size="sm"
                    block
                    className="mt-3"
                    onClick={() => navigate("/command")}
                  >
                    Review approval queue
                  </Button>
                </div>
              </div>
            </div>
          )}

          {activeTab === "evidence" && incidentId && (
            <EvidencePanel incidentId={incidentId} />
          )}

          {activeTab === "prediction" && incidentId && (
            <WhatIfSimulation
              zoneId={incident.zone_id || ""}
              incidentId={incidentId}
              disasterType={incident.disaster_type || "flood"}
            />
          )}

          {activeTab === "resources" && incidentId && (
            <ResourcePanel zoneId={incident.zone_id || null} incidentId={incidentId} />
          )}

          {activeTab === "route" && incidentId && (
            <RouteIntelligence zoneId={incident.zone_id || ""} incidentId={incidentId} />
          )}

          {activeTab === "audit" && (
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="ops-panel-flat">
                <div className="ops-panel-header">
                  <div>
                    <div className="ops-kicker">Evidence trail</div>
                    <div className="ops-title-sm">Field reports ({auditReports?.total ?? 0})</div>
                  </div>
                </div>
                <div className="ops-scroll-y" style={{ maxHeight: 360 }}>
                  {!auditReports ? (
                    <LoadingState label="Loading reports…" />
                  ) : auditReports.reports.length === 0 ? (
                    <EmptyState
                      title="No linked reports"
                      message="Reports ingested for this incident will appear here."
                    />
                  ) : (
                    auditReports.reports.map((r, i) => (
                      <div key={r.report_id ?? r.id ?? i} className="ops-list-item">
                        <span className="ops-mono shrink-0 text-xs text-slate-500">
                          #{i + 1}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="ops-clamp-2 block text-xs text-slate-200">
                            {r.excerpt || r.summary || r.message_text || r.transcript || "(empty)"}
                          </span>
                          <span className="ops-mono mt-1 block text-[11px] text-slate-500">
                            {r.source || "unknown"} ·{" "}
                            {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                            {r.suppressed ? " · suppressed" : ""}
                          </span>
                        </span>
                        {r.trust_score != null && (
                          <Badge
                            tone={
                              r.trust_score >= 0.7
                                ? "cyan"
                                : r.trust_score >= 0.4
                                  ? "amber"
                                  : "red"
                            }
                          >
                            {r.trust_score.toFixed(2)}
                          </Badge>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="ops-panel-flat">
                <div className="ops-panel-header">
                  <div>
                    <div className="ops-kicker">Decision audit</div>
                    <div className="ops-title-sm">Approval actions</div>
                  </div>
                  <Button size="sm" onClick={() => navigate("/command")}>
                    Open queue
                  </Button>
                </div>
                <div className="ops-panel-body space-y-3">
                  <div className="ops-stat" style={{ minHeight: "auto" }}>
                    <div className="ops-stat-label">Decision ID</div>
                    <div className="ops-mono mt-1 break-all text-sm text-slate-200">
                      {incident.incident_id}
                    </div>
                  </div>
                  <div className="ops-stat" style={{ minHeight: "auto" }}>
                    <div className="ops-stat-label">Model / engine</div>
                    <div className="ops-mono mt-1 text-sm text-slate-200">
                      decision_engine_v2 · conf {(incident.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="ops-stat" style={{ minHeight: "auto" }}>
                    <div className="ops-stat-label">Pending for this incident</div>
                    <div className="ops-mono mt-1 text-sm text-slate-200">
                      {pendingForIncident.length} action(s)
                      {pendingForIncident.length > 0 && (
                        <span className="text-[#f3b562]"> · approval required</span>
                      )}
                    </div>
                  </div>
                  <p className="text-xs leading-5 text-slate-400">
                    PRD §9: The LLM cannot approve, reject, or bypass the human approval gate.
                    Every approval writes an immutable audit record with user, role, and timestamp.
                  </p>
                  {pendingForIncident.map((action) => (
                    <div key={action.action_id} className="ops-list-item">
                      <PriorityBadge
                        score={action.priority_score}
                        band={action.priority_band}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="ops-clamp-2 block text-xs text-slate-200">
                          {action.description || action.action_type}
                        </span>
                        <span className="ops-mono mt-1 block text-[11px] text-slate-500">
                          {action.action_type} · {action.recommended_by} ·{" "}
                          {action.created_at
                            ? new Date(action.created_at).toLocaleString()
                            : "—"}
                        </span>
                      </span>
                      <Badge tone="amber">{action.status}</Badge>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
};
