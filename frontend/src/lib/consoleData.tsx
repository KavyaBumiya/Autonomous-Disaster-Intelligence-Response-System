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
  EMPTY_ALLOCATION_PLAN,
  EMPTY_ALLOCATION_QUEUE,
  EMPTY_ALERTS,
  EMPTY_FORECAST_SERIES,
  EMPTY_KPIS,
  EMPTY_MARKERS,
  EMPTY_PREDICTION_SUMMARY,
  EMPTY_PRIORITY_ALERT,
  EMPTY_RESOURCE_SLOTS,
  EMPTY_ROUTES,
  EMPTY_TEAMS,
  EMPTY_ZONE_STATS,
  NO_DATA,
  UNAVAILABLE,
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
  useHazardMatrix,
  useHealth,
  useIncidents,
  useLiveFeedStatus,
  useLiveRefresh,
  usePredictions,
  usePrimaryZoneId,
  useResources,
  useReports,
  useRoutes,
  useTeamResources,
  useZoneNames,
  useZones,
} from "./hooks";
import type {
  ApprovalAction,
  HazardMatrixResponse,
  Incident,
  PredictionsResponse,
  Resource,
  Report,
  Zone,
} from "./types";
import { useDashboardAI, type DashboardAIBrief } from "./useDashboardAI";

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
}

/** Published console state. */
export interface ConsoleData {
  /** Primary zone the console focuses on, resolved from the backend. */
  zoneId: string | null;
  zoneName: string;
  /** Full zone record, for coordinates and radius. */
  zone: Zone | null;

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
  reports: Report[] | null;
  predictions: PredictionsResponse | null;
  /** All modelled hazards for the selected zone, in one uniform envelope. */
  hazardMatrix: HazardMatrixResponse | null;
  dashboardAI: DashboardAIBrief;
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
  const reports = useReports(zoneId ?? undefined);
  const teamResources = useTeamResources();
  const available = useAvailableResources();
  const approvalQueue = useApprovalQueue();
  const predictions = usePredictions(zoneId);
  const hazardMatrix = useHazardMatrix(zoneId);
  const routes = useRoutes(zoneId);
  const zoneNames = useZoneNames(zones.data);
  // Real socket state, so the health badge reflects the live channel rather than
  // just the REST poll that keeps working while the socket is down.
  const liveFeedStatus = useLiveFeedStatus();

  useLiveRefresh([
    health, commandHealth, zones, incidents, resources, reports,
    teamResources, available, approvalQueue, predictions, hazardMatrix, routes,
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

  const dashboardAIResource = useDashboardAI(
    zoneId,
    topIncident,
    Boolean(commandHealth.data?.ai_available),
  );
  const dashboardAI = dashboardAIResource.data ?? {
    activeEmergency: false,
    title: "No Emergency Yet",
    summary: "AegisAI has not identified an active emergency for the selected zone.",
    preparations: [],
    raw: "",
  };

  // A failed read must never render as a plausible-looking number. True zeros
  // keep the cards honest; the degraded banner explains why they are empty.
  const slotTotals = useMemo(
    () =>
      resources.error
        ? EMPTY_RESOURCE_SLOTS
        : resourceSlotTotals(resources.data),
    [resources.data, resources.error],
  );

  const resourceCards = useMemo(
    () => toResourceCards(visuals.resourceSlots, slotTotals),
    [visuals.resourceSlots, slotTotals],
  );

  const alerts = useMemo(() => {
    const rows = toAlertRows(incidents.data);
    return incidents.error ? EMPTY_ALERTS : rows;
  }, [incidents.data, incidents.error]);

  const routeRows = useMemo(() => {
    const rows = toRouteRows(routes.data);
    return routes.error ? EMPTY_ROUTES : rows;
  }, [routes.data, routes.error]);

  const teamRows = useMemo(() => {
    const rows = toTeamRows(teamResources.data, zones.data, zoneNames);
    return teamResources.error ? EMPTY_TEAMS : rows;
  }, [teamResources.data, zones.data, zoneNames, teamResources.error]);

  const kpis = useMemo(
    () =>
      incidents.error || incidents.isInitialLoading
        ? EMPTY_KPIS
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
          // had a payload (offline, still loading, or erroring) we say so
          // rather than implying a specific flood is underway.
          incidents.data
            ? toPriorityAlert(null, null, 0)
            : EMPTY_PRIORITY_ALERT,
    [topIncident, predictions.data, evidenceStreams, incidents.data],
  );

  // No pending approval means no recommendation. An empty list is the honest
  // result; previously this rendered pre-written advice as if it were the
  // Decision Engine's current advice.
  const recommendations = useMemo<RecommendationRow[]>(
    () =>
      approvalQueue.error
        ? []
        : toRecommendations(approvalQueue.data?.actions ?? null),
    [approvalQueue.data, approvalQueue.error],
  );

  const allocationQueue = useMemo(() => {
    const rows = toAllocationQueue(approvalQueue.data?.actions ?? null);
    return approvalQueue.error ? EMPTY_ALLOCATION_QUEUE : rows;
  }, [approvalQueue.data, approvalQueue.error]);

  const allocationPlan = useMemo(() => {
    const rows = toRecommendations(approvalQueue.data?.actions ?? null, 4).map((row) => row.text);
    return approvalQueue.error ? EMPTY_ALLOCATION_PLAN : rows;
  }, [approvalQueue.data, approvalQueue.error]);

  const constraints = useMemo(
    () =>
      resources.error
        ? visuals.constraintTitles.map((title, index) => ({
            title,
            value: "0%",
            status: NO_DATA,
          }))
        : toConstraints(slotTotals, [...visuals.constraintTitles]),
    [resources.data, resources.error, slotTotals, visuals.constraintTitles],
  );

  const pressure = useMemo(
    () =>
      resources.error
        ? visuals.pressureLabels.map((label) => ({
            label,
            value: UNAVAILABLE,
            note: NO_DATA,
          }))
        : toSupplyPressure(slotTotals, [...visuals.pressureLabels]),
    [resources.data, resources.error, slotTotals, visuals.pressureLabels],
  );

  const forecastSeries = useMemo(
    () => toForecastSeries(predictions.data?.last_flood?.affected_cells ?? null) ?? EMPTY_FORECAST_SERIES,
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
        : // No projection payload at all: report nothing rather than a
          // confident "LOW RISK, 1 min, 0 people".
          { ...EMPTY_PREDICTION_SUMMARY },
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
    if (incidents.error || resources.error) return EMPTY_MARKERS;
    const pins = toMapMarkers({
      zone,
      incidents: incidents.data,
      resources: resources.data,
      floodCells: predictions.data?.last_flood?.affected_cells ?? null,
    });
    return pins ?? [];
  }, [zone, incidents.data, incidents.error, resources.data, resources.error, predictions.data]);

  const feedHealth = useMemo(
    () => toFeedHealth(health.data, liveFeedStatus),
    [health.data, liveFeedStatus],
  );

  const freshness = useMemo(() => {
    const stamps = [
      health.lastUpdatedAt,
      commandHealth.lastUpdatedAt,
      zones.lastUpdatedAt,
      incidents.lastUpdatedAt,
      resources.lastUpdatedAt,
      reports.lastUpdatedAt,
      teamResources.lastUpdatedAt,
      available.lastUpdatedAt,
      approvalQueue.lastUpdatedAt,
      predictions.lastUpdatedAt,
      routes.lastUpdatedAt,
    ].filter((value): value is number => typeof value === "number");
    if (stamps.length === 0) return "—";
    return `${Math.max(0, Math.round((Date.now() - Math.max(...stamps)) / 1000))}s`;
  }, [
    health.lastUpdatedAt,
    commandHealth.lastUpdatedAt,
    zones.lastUpdatedAt,
    incidents.lastUpdatedAt,
    resources.lastUpdatedAt,
    reports.lastUpdatedAt,
    teamResources.lastUpdatedAt,
    available.lastUpdatedAt,
    approvalQueue.lastUpdatedAt,
    predictions.lastUpdatedAt,
    routes.lastUpdatedAt,
  ]);

  const zoneStats = useMemo<ZoneStats>(() => {
    if (!zone && !topIncident) return EMPTY_ZONE_STATS;
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
      reports.refresh();
      dashboardAIResource.refresh();
      teamResources.refresh();
      available.refresh();
      approvalQueue.refresh();
      predictions.refresh();
      hazardMatrix.refresh();
      routes.refresh();
    },
    [health, commandHealth, zones, incidents, resources, reports, dashboardAIResource, teamResources, available, approvalQueue, predictions, hazardMatrix, routes],
  );

  const value = useMemo<ConsoleData>(
    () => ({
      zoneId,
      zoneName: zone?.name ?? "No zone selected",
      zone,
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
      reports: reports.data,
      predictions: predictions.data,
      hazardMatrix: hazardMatrix.data,
      dashboardAI,
      pendingActions: approvalQueue.data?.actions ?? [],
      topIncident,
      selectedIncidentFor: (alert) => findIncidentForAlert(incidents.data, alert),
      isDegraded:
        Boolean(incidents.error) ||
        Boolean(resources.error) ||
        Boolean(health.error) ||
        Boolean(zones.error) ||
        Boolean(reports.error) ||
        Boolean(predictions.error) ||
        Boolean(hazardMatrix.error) ||
        Boolean(routes.error) ||
        Boolean(approvalQueue.error) ||
        Boolean(teamResources.error) ||
        Boolean(available.error) ||
        Boolean(commandHealth.error),
      isInitialLoading:
        incidents.isInitialLoading &&
        resources.isInitialLoading &&
        zones.isInitialLoading &&
        reports.isInitialLoading &&
        predictions.isInitialLoading &&
        routes.isInitialLoading &&
        approvalQueue.isInitialLoading &&
        teamResources.isInitialLoading &&
        available.isInitialLoading &&
        health.isInitialLoading &&
        commandHealth.isInitialLoading,
      refreshAll,
      aiAvailable: commandHealth.data?.ai_available ?? false,
    }),
    [
      zoneId, zone, alerts, resourceCards, routeRows, teamRows, kpis, priorityAlert,
      recommendations, allocationQueue, allocationPlan, constraints, pressure,
      forecastSeries, evidenceRows, markers, feedHealth, zoneStats, freshness,
      predictionSummary, readiness, availability, incidents.data, resources.data,
      topIncident, health.error, zones.error, incidents.error, resources.error, reports.data,
      reports.error, predictions.error, hazardMatrix.error, routes.error, approvalQueue.error,
      teamResources.error, available.error, commandHealth.error,
      incidents.isInitialLoading, resources.isInitialLoading, zones.isInitialLoading,
      reports.isInitialLoading, predictions.isInitialLoading, routes.isInitialLoading,
      approvalQueue.isInitialLoading, teamResources.isInitialLoading,
      available.isInitialLoading, health.isInitialLoading, commandHealth.isInitialLoading,
      refreshAll, commandHealth.data, approvalQueue.data, predictions.data, hazardMatrix.data, dashboardAI, reports.data,
    ],
  );

  return <ConsoleDataContext.Provider value={value}>{children}</ConsoleDataContext.Provider>;
}
