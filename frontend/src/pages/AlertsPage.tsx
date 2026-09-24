import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { commandApi, incidentsApi, reportsApi, type Incident } from "@/services/api";
import { AppShell } from "@/components/AppShell";
import { Badge, Button, EmptyState, LoadingState, PriorityBadge } from "@/components/ui";

interface AlertRow {
  id: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  action?: { label: string; to: string };
}

export const AlertsPage: React.FC = () => {
  const navigate = useNavigate();

  const { data: critical } = useQuery({
    queryKey: ["command", "critical"],
    queryFn: async () => (await commandApi.critical(70, 10)).data,
    refetchInterval: 20000,
  });

  const { data: queue } = useQuery({
    queryKey: ["approval-queue"],
    queryFn: async () => (await commandApi.approvalQueue()).data,
    refetchInterval: 15000,
  });

  const { data: lowTrust } = useQuery({
    queryKey: ["reports", "low-trust"],
    queryFn: async () =>
      (await reportsApi.list({ min_trust: 0, limit: 50, include_suppressed: true })).data,
    refetchInterval: 30000,
  });

  const { data: activeIncidents } = useQuery<{ incidents: Incident[]; total: number }>({
    queryKey: ["incidents", "active"],
    queryFn: async () => (await incidentsApi.list({ active_only: true, limit: 200 })).data,
    refetchInterval: 30000,
  });

  const alerts: AlertRow[] = [];

  (critical?.incidents ?? []).forEach((inc) => {
    alerts.push({
      id: `crit-${inc.incident_id}`,
      severity: "critical",
      title: `${inc.disaster_type || "Incident"} above priority 70`,
      detail: `Priority ${inc.priority_score}/100 · zone ${inc.zone_id?.slice(0, 8)} · ${inc.victim_count || 0} victims`,
      action: { label: "Open incident", to: `/incidents/${inc.incident_id}` },
    });
  });

  if ((queue?.pending_count ?? 0) > 0) {
    alerts.push({
      id: "approvals",
      severity: "warning",
      title: `${queue?.pending_count} actions awaiting approval`,
      detail: "Human approval gate — AI cannot dispatch without commander sign-off.",
      action: { label: "Review queue", to: "/command" },
    });
  }

  const suppressed = (lowTrust?.reports ?? []).filter((r) => r.suppressed);
  if (suppressed.length > 0) {
    alerts.push({
      id: "suppressed",
      severity: "warning",
      title: `${suppressed.length} reports suppressed by trust filter`,
      detail: "Low-trust field reports were withheld from incident scoring.",
      action: { label: "Open dashboard", to: "/dashboard" },
    });
  }

  (activeIncidents?.incidents ?? [])
    .filter((inc) => (inc.victim_count ?? 0) > 0)
    .slice(0, 5)
    .forEach((inc) => {
      alerts.push({
        id: `vic-${inc.incident_id}`,
        severity: "info",
        title: `Victims detected — ${inc.disaster_type || "incident"}`,
        detail: `${inc.victim_count} detected (conf ${((inc.victim_confidence || 0) * 100).toFixed(0)}%) in zone ${inc.zone_id?.slice(0, 8)}`,
        action: { label: "View", to: `/incidents/${inc.incident_id}` },
      });
    });

  const isLoading = !critical && !queue && !activeIncidents;
  const tone = (s: AlertRow["severity"]) =>
    s === "critical" ? "red" : s === "warning" ? "amber" : "blue";

  return (
    <AppShell alertCount={alerts.filter((a) => a.severity !== "info").length}>
      <section className="fade-in mb-6">
        <div className="ops-kicker mb-2">Situation</div>
        <h1 className="text-3xl font-bold tracking-tight">Alerts</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          Priority breaches, pending approvals, trust suppressions, and victim detections —
          derived live from the same APIs as the dashboard.
        </p>
      </section>

      <div className="ops-panel">
        <div className="ops-panel-header">
          <div>
            <div className="ops-kicker">Feed</div>
            <div className="ops-title">Active alerts</div>
          </div>
          <Badge tone={alerts.length ? "red" : "cyan"}>{alerts.length} open</Badge>
        </div>

        {isLoading ? (
          <LoadingState label="Loading alerts…" />
        ) : alerts.length === 0 ? (
          <EmptyState
            title="All clear"
            message="No critical incidents, pending approvals, or suppressed reports right now."
          />
        ) : (
          <div>
            {alerts.map((alert) => (
              <div key={alert.id} className="ops-list-item">
                <PriorityBadge
                  score={alert.severity === "critical" ? 85 : alert.severity === "warning" ? 55 : 25}
                  band={alert.severity.toUpperCase()}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-white">{alert.title}</span>
                  <span className="ops-mono mt-1 block text-xs text-slate-400">{alert.detail}</span>
                </span>
                {alert.action && (
                  <Button size="sm" onClick={() => navigate(alert.action!.to)}>
                    {alert.action.label}
                  </Button>
                )}
                <span className={`ops-badge ops-badge-${tone(alert.severity)} hidden sm:inline-flex`}>
                  {alert.severity}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
};
