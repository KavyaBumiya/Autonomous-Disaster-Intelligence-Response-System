/**
 * Offline / empty-state values.
 *
 * These are the console's original hard-coded figures, kept verbatim so that
 * when the backend is unreachable, slow or has no rows yet, every panel renders
 * exactly what it rendered before the API was wired in. The UI never shows an
 * empty shell or a NaN; it falls back to this.
 */
import type { AlertRow, MapMarker, PriorityAlert, RouteRow, TeamRow } from "./mappers";

/** Seed incident feed, matching the previous `alerts` constant. */
export const FALLBACK_ALERTS: AlertRow[] = [
  { id: "AL-204", level: "CRITICAL", title: "Flash flood risk", place: "Sabarmati river belt", time: "2m ago", confidence: 94, status: "Active" },
  { id: "AL-203", level: "HIGH", title: "Road blockage detected", place: "Ashram Road → Paldi", time: "7m ago", confidence: 89, status: "Verified" },
  { id: "AL-202", level: "HIGH", title: "Shelter capacity falling", place: "Ward 18 relief camp", time: "11m ago", confidence: 91, status: "Monitoring" },
  { id: "AL-201", level: "MEDIUM", title: "Crowd density rising", place: "Riverfront East", time: "18m ago", confidence: 86, status: "Monitoring" },
  { id: "AL-200", level: "MEDIUM", title: "Power disruption", place: "Paldi sector", time: "24m ago", confidence: 83, status: "Verified" },
];

/** Seed route list, matching the previous `routes` constant. */
export const FALLBACK_ROUTES: RouteRow[] = [
  { name: "North rescue corridor", status: "CLEAR", eta: "14 min", detail: "3 checkpoints · 4.2 km" },
  { name: "Ashram Road → Paldi", status: "BLOCKED", eta: "—", detail: "Flooded at 2 points" },
  { name: "Relief camp supply route", status: "SLOW", eta: "26 min", detail: "+8 min traffic" },
  { name: "Ellis Bridge → Ward 18", status: "CLEAR", eta: "18 min", detail: "Preferred ambulance route" },
];

/** Seed team list, matching the previous `teams` constant. */
export const FALLBACK_TEAMS: TeamRow[] = [
  { name: "Rescue Team 04", type: "Urban Search & Rescue", people: 8, status: "DEPLOYED", zone: "Ellis Bridge", eta: "8 min" },
  { name: "Medical Unit 07", type: "Emergency Medical", people: 5, status: "STANDBY", zone: "Civil Hospital", eta: "12 min" },
  { name: "NGO Relief 12", type: "Food & Water", people: 11, status: "EN ROUTE", zone: "Ward 18", eta: "21 min" },
  { name: "Rescue Team 09", type: "Flood Response", people: 7, status: "DEPLOYED", zone: "Riverfront", eta: "6 min" },
];

/**
 * Resource card baselines. The icons themselves live in the UI; these are the
 * value/total pairs the cards rendered before wiring. `total` is never 0.
 */
export const FALLBACK_RESOURCE_SLOTS = {
  teams: { value: 18, total: 24 },
  vehicles: { value: 9, total: 12 },
  food: { value: 640, total: 900 },
  water: { value: 410, total: 600 },
} as const;

/** Forecast timeline bars. */
export const FALLBACK_FORECAST_SERIES = [22, 31, 43, 61, 74, 89, 96];

/** Prediction-page tiles and risk chip, as shown before the wiring. */
export const FALLBACK_PREDICTION_SUMMARY = {
  confidence: "94%",
  impactWindow: "42 min",
  population: "3,200",
  trend: "Rising",
  riskBand: "HIGH RISK",
  floodPercent: "0%",
} as const;

/**
 * Priority-alert card baseline. Distinct from a genuinely empty feed, which
 * renders "No active incident" — this one is what the card showed while the
 * console was still hard-coded.
 */
export const FALLBACK_PRIORITY_ALERT: PriorityAlert = {
  title: "Flash flood risk",
  etaMinutes: 42,
  people: "3,200",
  confidence: "94%",
  evidenceStreams: 3,
  narrative:
    "AI projects flood escalation within 42 min. 3,200 people fall inside the " +
    "projected impact zone for the Sabarmati river belt.",
};

/** Canvas pins. */
export const FALLBACK_MARKERS: MapMarker[] = [
  { x: 245, y: 180, c: "#ff5c69", label: "FLD" },
  { x: 610, y: 310, c: "#ffbd5a", label: "BLK" },
  { x: 420, y: 360, c: "#39d9ff", label: "SHELTER" },
  { x: 745, y: 145, c: "#35d39a", label: "TEAM" },
];

/** Overview tiles, matching the previous inline values. */
export const FALLBACK_KPIS = {
  activeIncidents: 7,
  criticalIncidents: 2,
  predictionConfidence: "94%",
  predictionSub: "Flash flood model",
  peopleAtRisk: "12.4K",
  peopleAtRiskSub: "↓ 8% from last update",
  unitsDeployed: "41 / 54",
  unitsDeployedSub: "76% capacity",
};

/** AI recommendation rows. */
export const FALLBACK_RECOMMENDATIONS = [
  { text: "Pre-position 2 rescue teams near Ellis Bridge.", confidence: "92%" },
  { text: "Reroute relief vehicles away from Paldi corridor.", confidence: "88%" },
  { text: "Reserve 180 water units for Ward 18.", confidence: "81%" },
];

/** Allocation queue lines. */
export const FALLBACK_ALLOCATION_QUEUE = [
  "2 rescue teams → Ellis Bridge",
  "180 water units → Ward 18",
  "3 ambulances → North corridor",
  "240 food kits → Riverfront shelter",
];

/** Commander allocation plan lines. */
export const FALLBACK_ALLOCATION_PLAN = [
  "Deploy 2 rescue teams to Ellis Bridge",
  "Reserve 180 water units for Ward 18",
  "Move 3 ambulances to North corridor",
  "Hold 240 food kits at Riverfront shelter",
];

/** Evidence category labels, and the confidences the console displayed. */
export const EVIDENCE_LABELS = [
  "River sensor trend",
  "Satellite moisture anomaly",
  "CCTV waterline detection",
  "Citizen reports",
  "Weather nowcast",
];

/** Constraint monitor titles, in the order the console listed them. */
export const CONSTRAINT_TITLES = [
  "Ambulance availability",
  "Rescue team coverage",
  "Water reserve",
  "Fuel stock",
];

/** Supply pressure labels and notes, in the order the console listed them. */
export const PRESSURE_LABELS = ["Water", "Medical kits", "Food", "Fuel"];
export const PRESSURE_NOTES = [
  "Reserve 180 units",
  "Stable",
  "Restock in 4 hr",
  "Priority replenishment",
];

/** Live-map selected-zone tile values. */
export const FALLBACK_ZONE_STATS = {
  risk: "HIGH",
  eta: "42 min",
  people: "3,200",
  confidence: "94%",
} as const;
