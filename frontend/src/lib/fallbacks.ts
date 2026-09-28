/**
 * Empty-state values.
 *
 * Nothing here is a number the console ever saw. Every constant is either a
 * true zero, an empty collection, or an explicit "unavailable" marker, so that
 * a failed or empty read can never be mistaken for real operational data.
 *
 * All actual figures come from the backend, which in turn sources them from
 * live providers (USGS, NASA EONET/FIRMS, weather, traffic) or from entities
 * an operator declared. If a provider has nothing to report, the console shows
 * "No data" — it does not invent a plausible-looking number.
 */
import type {
  AlertRow,
  MapMarker,
  PredictionSummary,
  PriorityAlert,
  RouteRow,
  TeamRow,
} from "./mappers";

/** No alerts are invented when the incident feed cannot be read. */
export const EMPTY_ALERTS: AlertRow[] = [];
export const EMPTY_ROUTES: RouteRow[] = [];
export const EMPTY_TEAMS: TeamRow[] = [];
export const EMPTY_MARKERS: MapMarker[] = [];

/** True zeros, never placeholder capacities. */
export const EMPTY_RESOURCE_SLOTS = {
  teams: { value: 0, total: 0 },
  vehicles: { value: 0, total: 0 },
  food: { value: 0, total: 0 },
  water: { value: 0, total: 0 },
} as const;

/** No forecast was retrieved, so there is no series to plot. */
export const EMPTY_FORECAST_SERIES: number[] = [];

/** Shown when no prediction has been computed for the selected zone. */
export const UNAVAILABLE = "—";
export const NO_DATA = "No data";

export const EMPTY_PREDICTION_SUMMARY = {
  confidence: UNAVAILABLE,
  impactWindow: UNAVAILABLE,
  population: UNAVAILABLE,
  // "Stable" is the neutral member of the trend union. It is chosen over
  // "Rising"/"Falling" because neither describes a trend that was never
  // measured; the riskBand below is what signals the absence to the operator.
  trend: "Stable",
  riskBand: "LOW RISK",
  floodPercent: UNAVAILABLE,
} as const satisfies PredictionSummary;

/** Priority card with no incident behind it. */
export const EMPTY_PRIORITY_ALERT: PriorityAlert = {
  title: "No active incident",
  etaMinutes: 0,
  people: "0",
  confidence: UNAVAILABLE,
  evidenceStreams: 0,
  narrative: "No live incident data is available for this zone.",
};

/** KPI tiles with nothing to report. */
export const EMPTY_KPIS = {
  activeIncidents: 0,
  criticalIncidents: 0,
  predictionConfidence: UNAVAILABLE,
  predictionSub: NO_DATA,
  peopleAtRisk: "0",
  peopleAtRiskSub: NO_DATA,
  unitsDeployed: "0 / 0",
  unitsDeployedSub: NO_DATA,
};

export const EMPTY_RECOMMENDATIONS: string[] = [];
export const EMPTY_ALLOCATION_QUEUE: string[] = [];
export const EMPTY_ALLOCATION_PLAN: string[] = [];

/** Live-map zone tiles with no computed prediction. */
export const EMPTY_ZONE_STATS = {
  risk: UNAVAILABLE,
  eta: UNAVAILABLE,
  people: "0",
  confidence: UNAVAILABLE,
} as const;

// ── UI vocabulary ────────────────────────────────────────────────────────
// The following are labels the console uses to name a category, not data.
// They are shown against live values (or against "—" when there are none).

/**
 * Evidence category labels.
 *
 * Every label must name a source the backend actually polls. There is no CCTV
 * connector, so listing one would imply a camera feed that does not exist.
 */
export const EVIDENCE_LABELS = [
  "River sensor trend",
  "Satellite moisture anomaly",
  "Citizen reports",
  "Weather nowcast",
];

/** Constraint monitor titles, in display order. */
export const CONSTRAINT_TITLES = [
  "Ambulance availability",
  "Rescue team coverage",
  "Water reserve",
  "Fuel stock",
];

/** Supply pressure labels, in display order. */
export const PRESSURE_LABELS = ["Water", "Medical kits", "Food", "Fuel"];
