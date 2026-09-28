/**
 * Console data provider.
 *
 * Owns every backend read for the operator console and publishes fully-derived,
 * fallback-applied view models through context. `App.tsx` supplies only the
 * console's visual vocabulary (card labels, icons, evidence category names),
 * which keeps all design decisions in the UI and all data logic here.
 *
 * The provider renders no DOM, so wrapping the app in it changes nothing on
 * screen.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import {
  FALLBACK_ALLOCATION_PLAN,
  FALLBACK_ALLOCATION_QUEUE,
  FALLBACK_ALERTS,
  FALLBACK_FORECAST_SERIES,
  FALLBACK_KPIS,
  FALLBACK_MARKERS,
  FALLBACK_PREDICTION_SUMMARY,
  FALLBACK_PRIORITY_ALERT,
  FALLBACK_RECOMMENDATIONS,
  FALLBACK_RESOURCE_SLOTS,
  FALLBACK_ROUTES,
  FALLBACK_TEAMS,
  FALLBACK_ZONE_STATS,
} from "./fallbacks";
import { hasData, num } from "./format";
import {
  type AlertRow,
  type ConstraintRow,
  type EvidenceRow,
  type FeedHealth,
  type MapMarker,
  type OverviewKpis,
  type PredictionSummary,
  type PressureRow,
  type PriorityAlert,
  type RecommendationRow,
  type ResourceSlotId,
  type ResourceSlotVisual,
  type RouteRow,
  type TeamRow,
  findIncidentForAlert,
  resourceSlotTotals,
  teamReadiness,
  toAllocationQueue,
  toAlertRows,
  toConstraints,
  toEvidenceRows,
  toFeedHealth,
  toForecastSeries,
  toMapMarkers,
  toOverviewKpis,
  toPredictionSummary,
  toPriorityAlert,
  toRecommendations,
  toResourceCards,
  toRouteRows,
  toSupplyPressure,
  toTeamRows,
} from "./mappers";
import {
  useApprovalQueue,
  useAvailableResources,
  useCommandHealth,
  useHealth,
  useIncidents,
  useLiveRefresh,
  usePredictions,
  usePrimaryZoneId,
  useResources,
  useRoutes,
  useTeamResources,
  useZoneNames,
  useZones,
} from "./hooks";
import type { ApprovalAction, Incident, Resource } from "./types";

export type { ResourceSlotId, ResourceSlotVisual };

/** Live-map selected-zone tile values. */
export interface ZoneStats {
  risk: string;
  eta: string;
  people: string;
  confidence: string;
}

/** The console's visual vocabulary, supplied by the UI layer. */
export interface ConsoleVisuals {
  resourceSlots: readonly ResourceSlotVisual<unknown>[];
  evidenceLabels: readonly string[];
  constraintTitles: readonly string[];
  pressureLabels: readonly string[];
  pressureNotes: readonly string[];
}

/** Published console state. */
export interface ConsoleData {
  /** Primary zone the console focuses on, resolved from the backend. */
  zoneId: string | null;
  zoneName: string;

  alerts: AlertRow[];
  resourceCards: Array<ResourceSlotVisual<unknown> & { value: number; total: number }>;
  routeRows: RouteRow[];
  teamRows: TeamRow[];

  kpis: OverviewKpis;
  priorityAlert: PriorityAlert;
  recommendations: RecommendationRow[];
  allocationQueue: string[];
  allocationPlan: string[];
  constraints: ConstraintRow[];
  pressure: PressureRow[];
  forecastSeries: number[];
  evidenceRows: EvidenceRow[];
  markers: MapMarker[];
  feedHealth: FeedHealth;
  zoneStats: ZoneStats;
  freshness: string;
  /** Full prediction-page summary, already fallback-applied. */
  predictionSummary: PredictionSummary;
  riskBand: string;
  floodPercent: string;

  /** Counts backing the team-readiness tiles. */
  readiness: { available: number; deployed: number; standby: number };
  /** Rollup from the command center's available-resource endpoint. */
  availability: { total: number; capacity: number };

  /** Raw collections, exposed for detail reads and mutation flows. */
  incidents: Incident[] | null;
  resources: Resource[] | null;
  /** Pending commander actions awaiting human approval. */
  pendingActions: ApprovalAction[];
  /** Incident backing the top alert row, for explain/summarise reads. */
  topIncident: Incident | null;
  selectedIncidentFor: (alert: AlertRow) => Incident | null;

  /** True when at least one endpoint is currently failing. */
  isDegraded: boolean;
  isInitialLoading: boolean;
  /** Manual refresh for every panel. */
  refreshAll: () => void;
  /** AI gateway availability, for the assistant header chip. */
  aiAvailable: boolean;
}

const ConsoleDataContext = createContext<ConsoleData | null>(null);

export function useConsoleData(): ConsoleData {
  const value = useContext(ConsoleDataContext);
  if (!value) throw new Error("useConsoleData must be used inside <ConsoleDataProvider>");
  return value;
}

/** Offline baselines for the constraint and pressure panels. */
const OFFLINE_CONSTRAINT_VALUES = ["0%", "0%", "0%", "0%"];
const OFFLINE_CONSTRAINT_STATUS = ["Unknown", "Unknown", "Unknown", "Unknown"];
const OFFLINE_PRESSURE_VALUES = ["—", "—", "—", "—"];

export function ConsoleDataProvider({
  visuals,
  children,
}: {
  visuals: ConsoleVisuals;
  children: ReactNode;
}) {
  // ── Reads ──────────────────────────────────────────────────────────────
  const health = useHealth();
  const commandHealth = useCommandHealth();
  const zones = useZones();
  const zoneId = usePrimaryZoneId(zones.data);
  const incidents = useIncidents(zoneId ?? undefined);
  const resources = useResources(zoneId ?? undefined);
  const teamResources = useTeamResources();
  const available = useAvailableResources();
  const approvalQueue = useApprovalQueue();
  const predictions = usePredictions(zoneId);
  const routes = useRoutes(zoneId);
  const zoneNames = useZoneNames(zones.data);

  useLiveRefresh([
    health, commandHealth, zones, incidents, resources,
    teamResources, available, approvalQueue, predictions, routes,
  ]);

  // ── Derivation ─────────────────────────────────────────────────────────
  const zone = useMemo(
    () => zones.data?.find((candidate) => candidate.zone_id === zoneId) ?? zones.data?.[0] ?? null,
    [zoneId, zones.data],
  );

  const topIncident = useMemo(
    () =>
      [...(incidents.data ?? [])].sort(
        (a, b) => num(b.priority_score) - num(a.priority_score),
      )[0] ?? null,
    [incidents.data],
  );

  // With the backend unreachable we must show the numbers the console showed
  // before it was wired, not a zeroed rollup.
  const slotTotals = useMemo(
    () =>
      resources.error
        ? FALLBACK_RESOURCE_SLOTS
        : resourceSlotTotals(resources.data),
    [resources.data, resources.error],
  );

  const resourceCards = useMemo(
    () => toResourceCards(visuals.resourceSlots, slotTotals),
    [visuals.resourceSlots, slotTotals],
  );

  const alerts = useMemo(() => {
    const rows = toAlertRows(incidents.data);
    return incidents.error ? FALLBACK_ALERTS : rows;
  }, [incidents.data, incidents.error]);

  const routeRows = useMemo(() => {
    const rows = toRouteRows(routes.data);
    return routes.error ? FALLBACK_ROUTES : rows;
  }, [routes.data, routes.error]);

  const teamRows = useMemo(() => {
    const rows = toTeamRows(teamResources.data, zones.data, zoneNames);
    return teamResources.error ? FALLBACK_TEAMS : rows;
  }, [teamResources.data, zones.data, zoneNames, teamResources.error]);

  const kpis = useMemo(
    () =>
      incidents.error || incidents.isInitialLoading
        ? FALLBACK_KPIS
        : toOverviewKpis({
            incidents: incidents.data,
            zones: zones.data,
            resources: resources.data,
            maxIntensity: predictions.data?.last_flood?.max_intensity ?? null,
            disasterType: topIncident?.disaster_type ?? null,
          }),
    [incidents.data, incidents.error, incidents.isInitialLoading, zones.data, resources.data, predictions.data, topIncident],
  );

  const evidenceStreams = useMemo(
    () => (topIncident ? Math.max(1, Math.round(num(topIncident.report_count))) : 0),
    [topIncident],
  );

  const priorityAlert = useMemo(
    () =>
      topIncident
        ? toPriorityAlert(topIncident, predictions.data?.last_flood?.max_intensity ?? null, evidenceStreams)
        : // No incident row is not the same as no backend: when we have never
          // had a payload (offline, still loading, or erroring) keep the
          // original alert rather than claiming there is nothing wrong.
          incidents.data
            ? toPriorityAlert(null, null, 0)
            : FALLBACK_PRIORITY_ALERT,
    [topIncident, predictions.data, evidenceStreams, incidents.data],
  );

  const recommendations = useMemo(() => {
    const rows = toRecommendations(approvalQueue.data?.actions ?? null);
    return approvalQueue.error ? FALLBACK_RECOMMENDATIONS : rows;
  }, [approvalQueue.data, approvalQueue.error]);

  const allocationQueue = useMemo(() => {
    const rows = toAllocationQueue(approvalQueue.data?.actions ?? null);
    return approvalQueue.error ? FALLBACK_ALLOCATION_QUEUE : rows;
  }, [approvalQueue.data, approvalQueue.error]);

  const allocationPlan = useMemo(() => {
    const rows = toRecommendations(approvalQueue.data?.actions ?? null, 4).map((row) => row.text);
    return approvalQueue.error ? FALLBACK_ALLOCATION_PLAN : rows;
  }, [approvalQueue.data, approvalQueue.error]);

  const constraints = useMemo(
    () =>
      resources.error
        ? visuals.constraintTitles.map((title, index) => ({
            title,
            value: OFFLINE_CONSTRAINT_VALUES[index] ?? "0%",
            status: OFFLINE_CONSTRAINT_STATUS[index] ?? "Unknown",
          }))
        : toConstraints(slotTotals, [...visuals.constraintTitles]),
    [resources.data, resources.error, slotTotals, visuals.constraintTitles],
  );

  const pressure = useMemo(
    () =>
      resources.error
        ? visuals.pressureLabels.map((label, index) => ({
            label,
            value: OFFLINE_PRESSURE_VALUES[index] ?? "0%",
            note: visuals.pressureNotes[index] ?? "",
          }))
        : toSupplyPressure(slotTotals, [...visuals.pressureLabels], [...visuals.pressureNotes]),
    [resources.data, resources.error, slotTotals, visuals.pressureLabels, visuals.pressureNotes],
  );

  const forecastSeries = useMemo(
    () => toForecastSeries(predictions.data?.last_flood?.affected_cells ?? null) ?? FALLBACK_FORECAST_SERIES,
    [predictions.data],
  );

  const predictionSummary = useMemo<PredictionSummary>(
    () =>
      predictions.data
        ? toPredictionSummary(
            predictions.data.last_flood?.max_intensity ?? null,
            predictions.data.last_flood?.flooded_percentage ?? null,
            topIncident,
          )
        : // No projection payload at all: keep the pre-wiring figures rather
          // than reporting a confident "LOW RISK, 1 min, 0 people".
          { ...FALLBACK_PREDICTION_SUMMARY },
    [predictions.data, topIncident],
  );

  const evidenceRows = useMemo(
    () =>
      toEvidenceRows({
        weatherRisk: predictions.data?.last_flood?.flooded_percentage ?? null,
        satelliteIntensity: predictions.data?.last_flood?.max_intensity ?? null,
        victimConfidence: topIncident?.victim_confidence ?? null,
        reportTrust: topIncident?.avg_trust_score ?? null,
        socialShare: null,
        labels: [...visuals.evidenceLabels],
      }),
    [predictions.data, topIncident, visuals.evidenceLabels],
  );

  const markers = useMemo(() => {
    if (incidents.error || resources.error) return FALLBACK_MARKERS;
    const pins = toMapMarkers({
      zone,
      incidents: incidents.data,
      resources: resources.data,
      floodCells: predictions.data?.last_flood?.affected_cells ?? null,
    });
    return pins ?? [];
  }, [zone, incidents.data, incidents.error, resources.data, resources.error, predictions.data]);

  const feedHealth = useMemo(() => toFeedHealth(health.data), [health.data]);

  const freshness = useMemo(() => {
    const stamps = [incidents.lastUpdatedAt, resources.lastUpdatedAt, predictions.lastUpdatedAt]
      .filter((value): value is number => typeof value === "number");
    if (stamps.length === 0) return "—";
    return `${Math.max(0, Math.round((Date.now() - Math.max(...stamps)) / 1000))}s`;
  }, [incidents.lastUpdatedAt, resources.lastUpdatedAt, predictions.lastUpdatedAt]);

  const zoneStats = useMemo<ZoneStats>(() => {
    if (!zone && !topIncident) return FALLBACK_ZONE_STATS;
    return {
      risk:
        predictionSummary.riskBand === "HIGH RISK"
          ? "HIGH"
          : predictionSummary.riskBand === "MODERATE RISK"
            ? "MEDIUM"
            : "LOW",
      eta: predictionSummary.impactWindow,
      people: predictionSummary.population,
      confidence: predictionSummary.confidence,
    };
  }, [zone, topIncident, predictionSummary]);

  const readiness = useMemo(() => teamReadiness(teamResources.data), [teamResources.data]);

  const availability = useMemo(
    () => ({
      total: available.data?.total ?? 0,
      capacity: (available.data?.resources ?? []).reduce(
        (sum, resource) => sum + Math.max(0, Math.round(num(resource.capacity))),
        0,
      ),
    }),
    [available.data],
  );

  const refreshAll = useMemo(
    () => () => {
      health.refresh();
      commandHealth.refresh();
      zones.refresh();
      incidents.refresh();
      resources.refresh();
      teamResources.refresh();
      available.refresh();
      approvalQueue.refresh();
      predictions.refresh();
      routes.refresh();
    },
    [health, commandHealth, zones, incidents, resources, teamResources, available, approvalQueue, predictions, routes],
  );

  const value = useMemo<ConsoleData>(
    () => ({
      zoneId,
      zoneName: zone?.name ?? "No zone selected",
      alerts,
      resourceCards,
      routeRows,
      teamRows,
      kpis,
      priorityAlert,
      recommendations,
      allocationQueue,
      allocationPlan,
      constraints,
      pressure,
      forecastSeries,
      evidenceRows,
      markers,
      feedHealth,
      zoneStats,
      freshness,
      predictionSummary,
      riskBand: predictionSummary.riskBand,
      floodPercent: predictionSummary.floodPercent,
      readiness,
      availability,
      incidents: incidents.data,
      resources: resources.data,
      pendingActions: approvalQueue.data?.actions ?? [],
      topIncident,
      selectedIncidentFor: (alert) => findIncidentForAlert(incidents.data, alert),
      isDegraded:
        Boolean(incidents.error) ||
        Boolean(resources.error) ||
        Boolean(health.error) ||
        Boolean(zones.error),
      isInitialLoading:
        incidents.isInitialLoading && resources.isInitialLoading && zones.isInitialLoading,
      refreshAll,
      aiAvailable: commandHealth.data?.ai_available ?? false,
    }),
    [
      zoneId, zone, alerts, resourceCards, routeRows, teamRows, kpis, priorityAlert,
      recommendations, allocationQueue, allocationPlan, constraints, pressure,
      forecastSeries, evidenceRows, markers, feedHealth, zoneStats, freshness,
      predictionSummary, readiness, availability, incidents.data, resources.data,
      topIncident, health.error, zones.error, incidents.error, resources.error,
      incidents.isInitialLoading, resources.isInitialLoading, zones.isInitialLoading,
      refreshAll, commandHealth.data, approvalQueue.data,
    ],
  );

  return <ConsoleDataContext.Provider value={value}>{children}</ConsoleDataContext.Provider>;
}
