/**
 * Backend payload -> operator-console view models.
 *
 * The console was designed around a handful of fixed row shapes (an alert row, a
 * resource card, a route row, a team row). Rather than restyle the UI, these
 * mappers translate the API into exactly those shapes, so every existing
 * component keeps rendering identically — only the numbers become real.
 *
 * Two rules hold throughout:
 *  - Visual vocabulary (labels, units, icons, colours, status words) stays put.
 *    Only values are derived from data.
 *  - Every mapper degrades to a declared fallback rather than emitting NaN,
 *    null or an empty panel when the backend is slow, empty or unreachable.
 */
import {
  ageShort,
  clamp,
  compactCount,
  driveMinutes,
  haversineKm,
  hasData,
  humanise,
  num,
  percentFromRatio,
  relativeAge,
} from "./format";
import type {
  ApprovalAction,
  AvailableResource,
  Incident,
  PredictionCell,
  Resource,
  ResourceType,
  RouteLeg,
  RoutesResponse,
  Zone,
} from "./types";

// ── View models (identical to the console's existing row shapes) ─────────

/** Matches the console's `alerts` array. */
export interface AlertRow {
  id: string;
  level: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  title: string;
  place: string;
  time: string;
  confidence: number;
  status: "Active" | "Verified" | "Monitoring";
}

/** Matches the console's `resources` array (minus the icon, which is UI). */
export interface ResourceSlotValue {
  value: number;
  total: number;
}

/** Matches the console's `routes` array. */
export interface RouteRow {
  name: string;
  status: "CLEAR" | "BLOCKED" | "SLOW";
  eta: string;
  detail: string;
}

/** Matches the console's `teams` array. */
export interface TeamRow {
  name: string;
  type: string;
  people: number;
  status: "DEPLOYED" | "STANDBY" | "EN ROUTE";
  zone: string;
  eta: string;
}

/** Map canvas pin: same shape the inline SVG already renders. */
export interface MapMarker {
  x: number;
  y: number;
  c: string;
  label: string;
}

export type ResourceSlotId = "teams" | "vehicles" | "food" | "water";

// ── Shared derivations ───────────────────────────────────────────────────

/** Band label from a 0..100 score, using the backend's own thresholds. */
function bandFromScore(score: number): AlertRow["level"] {
  if (score >= 85) return "CRITICAL";
  if (score >= 70) return "HIGH";
  if (score >= 40) return "MEDIUM";
  return "LOW";
}

/**
 * Incident status word. The console styles exactly three, so unknown states
 * fall to "Monitoring" rather than rendering an unstyled token.
 */
function statusWord(incident: Pick<Incident, "status" | "active">): AlertRow["status"] {
  const status = (incident.status ?? "").toLowerCase();
  if (status === "active") return "Active";
  if (["resolved", "closed", "contained", "verified", "completed"].includes(status)) {
    return "Verified";
  }
  if (incident.active === false) return "Verified";
  return "Monitoring";
}

/** Human label for an incident's location, tolerating a missing zone. */
function placeLabel(incident: Incident): string {
  if (incident.zone_name) return incident.zone_name;
  const short = (incident.zone_id ?? "").slice(0, 8);
  return short ? `Zone ${short}` : "Unassigned zone";
}

/**
 * Incident confidence as a whole percentage. Prefers the incident's own
 * confidence, then the average report trust, then the victim confidence.
 */
function incidentConfidence(incident: Incident): number {
  if (incident.confidence !== null && incident.confidence !== undefined) {
    return Math.round(percentFromRatio(incident.confidence, 0));
  }
  if (incident.avg_trust_score !== null && incident.avg_trust_score !== undefined) {
    return Math.round(percentFromRatio(incident.avg_trust_score, 0));
  }
  return Math.round(percentFromRatio(incident.victim_confidence, 0));
}

// ── Incidents -> alert rows ──────────────────────────────────────────────

/** Convert one incident into a console alert row. */
export function toAlertRow(incident: Incident, now = Date.now()): AlertRow {
  const score = num(incident.priority_score);
  const declared = (incident.priority_band ?? "").toUpperCase();
  const level = (["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).find(
    (band) => band === declared,
  ) ?? bandFromScore(score);

  const stamped = incident.updated_at ?? incident.created_at;

  return {
    id: incident.incident_id,
    level,
    title: humanise(incident.disaster_type, "Unclassified incident"),
    place: placeLabel(incident),
    time: relativeAge(stamped, now) || "—",
    confidence: incidentConfidence(incident),
    status: statusWord(incident),
  };
}

/** Convert a list of incidents, highest priority first. */
export function toAlertRows(incidents: Incident[] | null, now = Date.now()): AlertRow[] {
  if (!hasData(incidents)) return [];
  return [...incidents]
    .sort((a, b) => num(b.priority_score) - num(a.priority_score))
    .map((incident) => toAlertRow(incident, now));
}

/** Index the live alert rows back onto their incidents for follow-up reads. */
export function findIncidentForAlert(
  incidents: Incident[] | null,
  alert: AlertRow | null,
): Incident | null {
  if (!alert || !hasData(incidents)) return null;
  return incidents.find((incident) => incident.incident_id === alert.id) ?? null;
}

// ── Resources -> resource cards ──────────────────────────────────────────

/**
 * Which backend resources feed which console card.
 *
 * The four cards are the console's fixed visual vocabulary, so the mapping lives
 * here while the label/icon/unit stay in the UI. "Ambulances" is a vehicle card
 * and "Food kits"/"Water units" are supply cards split by name.
 */
const slotMatchers: Record<ResourceSlotId, (r: Resource) => boolean> = {
  teams: (r) => r.resource_type === "team",
  vehicles: (r) => r.resource_type === "vehicle",
  food: (r) => r.resource_type === "supply" && /food|meal|ration|kit/i.test(r.name ?? ""),
  water: (r) => r.resource_type === "supply" && /water|drink|hydr/i.test(r.name ?? ""),
};

/** Free capacity = capacity minus current load, floored at zero. */
function freeCapacity(resource: Resource): number {
  return Math.max(0, Math.round(num(resource.capacity) - num(resource.current_load)));
}

/**
 * Sum available and total capacity per console card.
 *
 * `total` is floored at 1 because the console divides by it to size a progress
 * bar — a zero would render `NaN%` width.
 */
export function resourceSlotTotals(
  resources: Resource[] | null,
): Record<ResourceSlotId, ResourceSlotValue> {
  const totals: Record<ResourceSlotId, ResourceSlotValue> = {
    teams: { value: 0, total: 0 },
    vehicles: { value: 0, total: 0 },
    food: { value: 0, total: 0 },
    water: { value: 0, total: 0 },
  };
  if (!hasData(resources)) return totals;

  for (const resource of resources) {
    for (const slot of Object.keys(slotMatchers) as ResourceSlotId[]) {
      if (!slotMatchers[slot](resource)) continue;
      const capacity = Math.max(0, Math.round(num(resource.capacity)));
      totals[slot].total += capacity;
      if (resource.available) totals[slot].value += freeCapacity(resource);
    }
  }

  for (const slot of Object.keys(totals) as ResourceSlotId[]) {
    totals[slot].total = Math.max(1, totals[slot].total);
  }
  return totals;
}

/** Visual metadata for one resource card, owned by the UI (icon included). */
export interface ResourceSlotVisual<TIcon = unknown> {
  id: ResourceSlotId;
  label: string;
  icon: TIcon;
  unit: string;
}

/**
 * Bind the console's four resource cards to live capacity numbers.
 *
 * The card metadata (label, icon, unit) comes straight from the UI so the
 * design is unchanged; only value/total are data-driven. A slot the backend has
 * no rows for keeps a zeroed capacity of 1 so the progress bar stays valid.
 */
export function toResourceCards<TIcon>(
  slots: readonly ResourceSlotVisual<TIcon>[],
  totals: Record<ResourceSlotId, ResourceSlotValue>,
): Array<ResourceSlotVisual<TIcon> & ResourceSlotValue> {
  return slots.map((slot) => ({
    ...slot,
    value: totals[slot.id]?.value ?? 0,
    total: Math.max(1, totals[slot.id]?.total ?? 1),
  }));
}

/** Fleet-wide deployment rollup for the "Units deployed" tile. */
export function resourceDeployment(
  resources: Resource[] | null,
): { deployed: number; total: number } {
  if (!hasData(resources)) return { deployed: 0, total: 0 };
  let deployed = 0;
  let total = 0;
  for (const resource of resources) {
    total += Math.max(0, Math.round(num(resource.capacity)));
    deployed += clamp(num(resource.current_load), 0, num(resource.capacity, 0));
  }
  return { deployed, total };
}

/** Available-resource rollup for the command center endpoint's payload. */
export function availableResourceRollup(
  resources: AvailableResource[] | null,
): { total: number; capacity: number } {
  if (!hasData(resources)) return { total: 0, capacity: 0 };
  return {
    total: resources.length,
    capacity: resources.reduce((sum, r) => sum + Math.max(0, Math.round(num(r.capacity))), 0),
  };
}

// ── Routes -> route rows ─────────────────────────────────────────────────

/** Status word for a leg. Anything detouring around a blockage reads as blocked. */
function legStatus(leg: RouteLeg, isPrimary: boolean): RouteRow["status"] {
  if (isPrimary) return "CLEAR";
  if (/blocked/i.test(leg.detour_reason ?? "")) return "BLOCKED";
  return "SLOW";
}

/** ETA cell text, using the console's "—" for a route it cannot time. */
function legEta(leg: RouteLeg, isPrimary: boolean): string {
  if (!isPrimary && (leg.detour_reason ?? "").startsWith("Blocked")) return "—";
  return `${Math.max(0, Math.round(num(leg.estimated_minutes)))} min`;
}

/** Detail line: distance plus the routing reason, trimmed to one phrase. */
function legDetail(leg: RouteLeg): string {
  const km = num(leg.distance_km);
  const distance = `${km >= 10 ? Math.round(km) : km.toFixed(1)} km`;
  const reason = (leg.detour_reason ?? leg.note ?? "").trim();
  if (!reason) return distance;
  return `${distance} · ${reason.length > 44 ? `${reason.slice(0, 43)}…` : reason}`;
}

/**
 * Convert a route computation into console route rows: the primary corridor
 * first, then each alternate.
 */
export function toRouteRows(response: RoutesResponse | null): RouteRow[] {
  if (!response) return [];
  const zoneName = response.zone_name || "Response zone";
  const rows: RouteRow[] = [
    {
      name: `${zoneName} primary corridor`,
      status: legStatus(response.primary_route, true),
      eta: legEta(response.primary_route, true),
      detail: legDetail(response.primary_route),
    },
  ];

  response.alternate_routes.forEach((leg, index) => {
    rows.push({
      name: `${zoneName} alternate ${index + 1}`,
      status: legStatus(leg, false),
      eta: legEta(leg, false),
      detail: legDetail(leg),
    });
  });

  return rows;
}

/** Human-readable engine name for the routing chip. */
export function routeEngineLabel(response: RoutesResponse | null): string {
  if (!response) return "deterministic route planner";
  return response.engine === "osrm_route_planner_v1" ? "OSRM route planner" : "deterministic route planner";
}

// ── Resources -> team rows ───────────────────────────────────────────────

/** Map a team name onto the console's specialty vocabulary. */
function specialtyFor(name: string, type: ResourceType): string {
  const haystack = (name ?? "").toLowerCase();
  if (/rescue|usar|search/.test(haystack)) return "Urban Search & Rescue";
  if (/medical|medic|ambulance|doctor/.test(haystack)) return "Emergency Medical";
  if (/food|water|relief|ngo|supply/.test(haystack)) return "Food & Water";
  if (/flood|boat|dive/.test(haystack)) return "Flood Response";
  return humanise(type, "Field team");
}

/**
 * Team status, using the three states the console styles:
 *  - assigned to a zone and still carrying load -> DEPLOYED
 *  - idle with spare capacity                   -> STANDBY
 *  - loaded but unassigned                      -> EN ROUTE
 */
function teamStatus(resource: Resource): TeamRow["status"] {
  const loaded = num(resource.current_load) > 0;
  if (resource.assigned_zone_id) return "DEPLOYED";
  if (loaded) return "EN ROUTE";
  return "STANDBY";
}

/**
 * Convert team-typed resources into console team rows, including a drive-time
 * estimate when both the asset and the zone centroid are known.
 */
export function toTeamRows(
  teams: Resource[] | null,
  zones: Zone[] | null,
  zoneNameById?: Map<string, string>,
): TeamRow[] {
  if (!hasData(teams)) return [];
  const centroidById = new Map((zones ?? []).map((zone) => [zone.zone_id, zone]));

  return teams.map((team) => {
    const zone = team.assigned_zone_id ? centroidById.get(team.assigned_zone_id) : undefined;
    const zoneName = team.assigned_zone_id
      ? (zoneNameById?.get(team.assigned_zone_id) ?? zone?.name ?? "Assigned zone")
      : "Unassigned";

    let eta = "—";
    if (team.lat !== null && team.lng !== null && zone) {
      const km = haversineKm(zone.centroid_lat, zone.centroid_lng, team.lat, team.lng);
      eta = `${driveMinutes(km)} min`;
    }

    return {
      name: team.name || humanise(team.resource_type, "Field team"),
      type: specialtyFor(team.name, team.resource_type),
      people: Math.max(0, Math.round(num(team.current_load) || num(team.capacity))),
      status: teamStatus(team),
      zone: zoneName,
      eta,
    };
  });
}

/** Team readiness rollup for the sidebar stats. */
export function teamReadiness(teams: Resource[] | null): {
  available: number;
  deployed: number;
  standby: number;
} {
  if (!hasData(teams)) return { available: 0, deployed: 0, standby: 0 };
  let available = 0;
  let deployed = 0;
  let standby = 0;
  for (const team of teams) {
    if (teamStatus(team) === "DEPLOYED") deployed += 1;
    else if (teamStatus(team) === "EN ROUTE") available += 1;
    else standby += 1;
  }
  return { available, deployed, standby };
}

// ── Overview KPIs ────────────────────────────────────────────────────────

export interface OverviewKpis {
  activeIncidents: number;
  criticalIncidents: number;
  predictionConfidence: string;
  predictionSub: string;
  peopleAtRisk: string;
  peopleAtRiskSub: string;
  unitsDeployed: string;
  unitsDeployedSub: string;
}

export interface KpiInputs {
  incidents: Incident[] | null;
  zones: Zone[] | null;
  resources: Resource[] | null;
  maxIntensity: number | null;
  disasterType: string | null;
}

/** Build the four overview tiles. */
export function toOverviewKpis(input: KpiInputs): OverviewKpis {
  const incidents = input.incidents ?? [];
  const active = incidents.filter((incident) => incident.active);
  const critical = active.filter((incident) => bandFromScore(num(incident.priority_score)) === "CRITICAL");

  const topConfidence = active.length
    ? Math.max(...active.map(incidentConfidence))
    : 0;

  const peopleAtRisk = active.reduce((sum, incident) => sum + Math.max(0, num(incident.victim_count)), 0);
  const { deployed, total } = resourceDeployment(input.resources);
  const capacityPct = total > 0 ? Math.round((deployed / total) * 100) : 0;

  return {
    activeIncidents: active.length,
    criticalIncidents: critical.length,
    predictionConfidence: `${Math.round(clamp(topConfidence, 0, 100))}%`,
    predictionSub: input.disasterType ? `${humanise(input.disasterType)} model` : "hazard model",
    peopleAtRisk: compactCount(peopleAtRisk),
    peopleAtRiskSub: `${active.length} active incident${active.length === 1 ? "" : "s"}`,
    unitsDeployed: `${deployed} / ${total}`,
    unitsDeployedSub: `${capacityPct}% capacity`,
  };
}

// ── Priority alert ───────────────────────────────────────────────────────

export interface PriorityAlert {
  title: string;
  etaMinutes: number;
  people: string;
  confidence: string;
  evidenceStreams: number;
  narrative: string;
}

/** Compose the priority-alert card from the top incident plus its projection. */
export function toPriorityAlert(
  incident: Incident | null,
  maxIntensity: number | null,
  evidenceStreams: number,
): PriorityAlert {
  if (!incident) {
    return {
      title: "No active incident",
      etaMinutes: 0,
      people: "0",
      confidence: "0%",
      evidenceStreams: 0,
      narrative: "No active incident is currently above the response threshold.",
    };
  }

  const people = Math.max(0, num(incident.victim_count));
  const confidence = incidentConfidence(incident);
  // Impact window scales with hazard intensity: 100 intensity -> 60 min.
  const etaMinutes = maxIntensity === null ? 0 : Math.max(1, Math.round((clamp(maxIntensity, 0, 100) / 100) * 60));
  const riskWord = bandFromScore(num(incident.priority_score));

  return {
    title: `${humanise(incident.disaster_type, "Hazard")} risk`,
    etaMinutes,
    people: compactCount(people),
    confidence: `${confidence}%`,
    evidenceStreams: Math.max(0, Math.round(evidenceStreams)),
    narrative:
      `AI projects ${humanise(incident.disaster_type, "hazard")} escalation within ` +
      `${etaMinutes} min. ${compactCount(people)} people fall inside the projected impact zone ` +
      `for ${placeLabel(incident)}. Current band ${riskWord} with ${confidence}% confidence.`,
  };
}

// ── Recommendations / approval queue ─────────────────────────────────────

export interface RecommendationRow {
  text: string;
  confidence: string;
}

/** Turn pending approval actions into the console's recommendation rows. */
export function toRecommendations(
  actions: ApprovalAction[] | null,
  limit = 3,
): RecommendationRow[] {
  if (!hasData(actions)) return [];
  return actions.slice(0, limit).map((action) => ({
    text: action.description || `${humanise(action.action_type, "Recommended")} for this incident`,
    confidence: `${Math.round(clamp(action.priority_score, 0, 100))}%`,
  }));
}

/** Allocation-queue rows. The console badges these by index, so order is stable. */
export function toAllocationQueue(actions: ApprovalAction[] | null, limit = 4): string[] {
  if (!hasData(actions)) return [];
  return actions.slice(0, limit).map(
    (action) => action.description || `${humanise(action.action_type, "Allocate")} per resource commander`,
  );
}

// ── Predictions ──────────────────────────────────────────────────────────

/**
 * Fold prediction cells into the console's 7-bar forecast timeline.
 *
 * The engine emits one entry per cell at the hour it first floods; those hours
 * are bucketed into the timeline's 7 steps and each step takes the peak
 * intensity in its window. Returns null when there is nothing to plot so the
 * caller can keep its existing series instead of drawing an empty chart.
 */
export function toForecastSeries(
  cells: PredictionCell[] | null,
  bars = 7,
  horizonSteps = 12,
): number[] | null {
  if (!hasData(cells)) return null;

  const usable = cells.filter((cell) => num(cell.intensity) > 0);
  if (usable.length === 0) return null;

  const maxStep = Math.max(1, ...usable.map((cell) => Math.max(1, Math.round(num(cell.time_step, 1)))));
  const span = Math.max(maxStep, horizonSteps);

  const series = new Array<number>(bars).fill(0);
  for (const cell of usable) {
    const step = clamp(Math.round(num(cell.time_step, 1)), 0, span);
    const index = Math.min(bars - 1, Math.floor((step / span) * bars));
    series[index] = Math.max(series[index], clamp(num(cell.intensity), 0, 100));
  }
  return series.some((value) => value > 0) ? series : null;
}

export interface PredictionSummary {
  confidence: string;
  impactWindow: string;
  population: string;
  trend: "Rising" | "Falling" | "Stable";
  riskBand: "HIGH RISK" | "MODERATE RISK" | "LOW RISK";
  floodPercent: string;
}

/** Compose the prediction page's four stat tiles and risk chip. */
export function toPredictionSummary(
  maxIntensity: number | null,
  floodedPercentage: number | null,
  incident: Incident | null,
  previousMaxIntensity?: number | null,
): PredictionSummary {
  const intensity = clamp(maxIntensity, 0, 100);
  const previous = previousMaxIntensity === null || previousMaxIntensity === undefined
    ? null
    : clamp(previousMaxIntensity, 0, 100);

  const trend: PredictionSummary["trend"] =
    previous === null ? "Rising" : intensity > previous + 0.5 ? "Rising" : intensity < previous - 0.5 ? "Falling" : "Stable";

  const people = incident ? Math.max(0, num(incident.victim_count)) : 0;
  const confidence = incident ? incidentConfidence(incident) : Math.round(intensity);

  return {
    confidence: `${confidence}%`,
    impactWindow: `${Math.max(1, Math.round((intensity / 100) * 60))} min`,
    population: compactCount(people),
    trend,
    riskBand: intensity >= 60 ? "HIGH RISK" : intensity >= 30 ? "MODERATE RISK" : "LOW RISK",
    floodPercent: `${Math.round(clamp(floodedPercentage, 0, 100))}%`,
  };
}

export interface EvidenceRow {
  label: string;
  confidence: string;
}

/**
 * Attach real signal strength to the console's five fixed evidence categories.
 * Labels stay as designed; each percentage is backed by a live signal.
 */
export function toEvidenceRows(input: {
  weatherRisk?: number | null;
  satelliteIntensity?: number | null;
  victimConfidence?: number | null;
  reportTrust?: number | null;
  socialShare?: number | null;
  labels: string[];
}): EvidenceRow[] {
  const signals: Array<number | null | undefined> = [
    input.weatherRisk,
    input.satelliteIntensity,
    input.victimConfidence,
    input.reportTrust,
    input.socialShare,
  ];

  return input.labels.map((label, index) => {
    const signal = signals[index];
    const confidence =
      signal === null || signal === undefined ? 0 : Math.round(percentFromRatio(signal, 0));
    return { label, confidence: `${clamp(confidence, 0, 100)}%` };
  });
}

// ── Constraint monitor / supply pressure ─────────────────────────────────

export interface ConstraintRow {
  title: string;
  value: string;
  status: string;
}

/**
 * Fill the constraint monitor from real capacity pressure. Titles are the
 * console's fixed vocabulary; the bar value and status word come from data.
 */
export function toConstraints(
  totals: Record<ResourceSlotId, ResourceSlotValue>,
  titles: string[],
): ConstraintRow[] {
  const order: ResourceSlotId[] = ["vehicles", "teams", "water", "food"];
  return titles.map((title, index) => {
    const slot = order[index % order.length];
    const { value, total } = totals[slot];
    const pressure = total > 0 ? clamp(value / total, 0, 1) : 0;
    const pct = Math.round(pressure * 100);
    const status = pressure <= 0.35 ? "Low" : pressure <= 0.7 ? "Watch" : "Within limits";
    return { title, value: `${pct}%`, status };
  });
}

export interface PressureRow {
  label: string;
  value: string;
  note: string;
}

/** Supply pressure rows for the resources page. */
export function toSupplyPressure(
  totals: Record<ResourceSlotId, ResourceSlotValue>,
  labels: string[],
  notes: string[],
): PressureRow[] {
  const order: ResourceSlotId[] = ["water", "vehicles", "food", "teams"];
  return labels.map((label, index) => {
    const slot = order[index % order.length];
    const { value, total } = totals[slot];
    const pct = total > 0 ? Math.round(clamp(value / total, 0, 1) * 100) : 0;
    return { label, value: `${clamp(pct, 0, 100)}%`, note: notes[index] ?? "" };
  });
}

// ── Map markers ──────────────────────────────────────────────────────────

/** The canvas' fixed viewBox; markers are projected into this space. */
const VIEW_W = 900;
const VIEW_H = 520;
const PAD_X = 60;
const PAD_Y = 45;

interface LatLng {
  lat: number;
  lng: number;
}

/** Type-guard filter: backend coordinates are nullable, the projector is not. */
function hasCoords<T extends { lat: number | null; lng: number | null }>(
  row: T,
): row is T & LatLng {
  return row.lat !== null && row.lng !== null;
}

/**
 * Project coordinates into the canvas viewBox using a bounding box centred on
 * the primary zone, sized to the zone radius (or the observed point spread).
 */
function makeProjector(zone: Zone | null, points: LatLng[]): (p: LatLng) => { x: number; y: number } {
  const latSpan = Math.max(0.004, (num(zone?.radius_meters, 600) / 111_320));
  const lngSpan = Math.max(
    0.004,
    latSpan / Math.max(0.2, Math.cos(((zone?.centroid_lat ?? 20) * Math.PI) / 180)),
  );

  const centreLat = zone?.centroid_lat ?? (points.length ? points.reduce((s, p) => s + p.lat, 0) / points.length : 0);
  const centreLng = zone?.centroid_lng ?? (points.length ? points.reduce((s, p) => s + p.lng, 0) / points.length : 0);

  const toX = (lng: number) =>
    clamp(PAD_X + ((lng - (centreLng - lngSpan)) / (2 * lngSpan)) * (VIEW_W - 2 * PAD_X), PAD_X, VIEW_W - PAD_X);
  const toY = (lat: number) =>
    clamp(PAD_Y + (1 - (lat - (centreLat - latSpan)) / (2 * latSpan)) * (VIEW_H - 2 * PAD_Y), PAD_Y, VIEW_H - PAD_Y);

  return (point) => ({ x: Math.round(toX(point.lng)), y: Math.round(toY(point.lat)) });
}

/**
 * Build the four canvas pins from live data, keeping the console's existing
 * colour/label vocabulary: FLD (critical), BLK (warning), SHELTER, TEAM.
 * Returns null when there is not enough data, so the caller keeps its pins.
 */
export function toMapMarkers(input: {
  zone: Zone | null;
  incidents: Incident[] | null;
  resources: Resource[] | null;
  floodCells: PredictionCell[] | null;
  shelterResources?: Resource[] | null;
}): MapMarker[] | null {
  const incidents = (input.incidents ?? []).filter(hasCoords);
  const located = (input.resources ?? []).filter(hasCoords);
  const cells = input.floodCells ?? [];
  const shelters = (input.shelterResources ?? input.resources ?? []).filter(
    (r): r is Resource & LatLng => r.resource_type === "shelter" && hasCoords(r),
  );

  const project = makeProjector(input.zone, [...incidents, ...located, ...cells]);
  const markers: MapMarker[] = [];

  const peakCell = cells.length
    ? cells.reduce((best, cell) => (num(cell.intensity) > num(best.intensity) ? cell : best), cells[0])
    : null;
  if (peakCell) {
    const { x, y } = project(peakCell);
    markers.push({ x, y, c: "#ff5c69", label: "FLD" });
  }

  const blocked = incidents.find((incident) => bandFromScore(num(incident.priority_score)) === "HIGH" && !incidents[0]?.active);
  if (blocked) {
    const { x, y } = project({ lat: num(blocked.lat), lng: num(blocked.lng) });
    markers.push({ x, y, c: "#ffbd5a", label: "BLK" });
  }

  const shelter = shelters[0];
  if (shelter) {
    const { x, y } = project({ lat: num(shelter.lat), lng: num(shelter.lng) });
    markers.push({ x, y, c: "#39d9ff", label: "SHELTER" });
  }

  const team = located.find((r) => r.resource_type === "team") ?? located[0];
  if (team) {
    const { x, y } = project({ lat: num(team.lat), lng: num(team.lng) });
    markers.push({ x, y, c: "#35d39a", label: "TEAM" });
  }

  return markers.length > 0 ? markers.slice(0, 4) : null;
}

// ── Health / live-feed indicators ────────────────────────────────────────

export interface FeedHealth {
  statusLabel: string;
  streamLabel: string;
  systemLabel: string;
  sourceCount: number;
  healthyFeeds: number;
  isNominal: boolean;
}

/** Derive the header/sidebar liveness indicators from GET /api/health. */
export function toFeedHealth(health: {
  status?: string;
  providers?: Record<string, { status?: string }>;
  services?: Record<string, string>;
} | null): FeedHealth {
  if (!health) {
    return {
      statusLabel: "Backend unreachable",
      streamLabel: "—",
      systemLabel: "System offline",
      sourceCount: 0,
      healthyFeeds: 0,
      isNominal: false,
    };
  }

  const providers = health.providers ?? {};
  const entries = Object.values(providers);
  const healthy = entries.filter((p) => p.status === "ONLINE").length;
  const canonical = entries.filter((p) => (p as { canonical?: boolean }).canonical).length;
  const services = health.services ?? {};
  const isNominal = health.status === "ok" && services.database === "ONLINE";

  return {
    statusLabel: isNominal ? "Data stream healthy" : "Data stream degraded",
    streamLabel: `${healthy} live feeds`,
    systemLabel: isNominal ? "System nominal" : "System degraded",
    sourceCount: canonical || entries.length,
    healthyFeeds: healthy,
    isNominal,
  };
}

// ── Misc ─────────────────────────────────────────────────────────────────

/** Last-seen text for the sidebar sync line, e.g. "8s". */
export function freshnessLabel(lastUpdatedAt: number | null, now = Date.now()): string {
  if (!lastUpdatedAt) return "—";
  return ageShort(new Date(lastUpdatedAt).toISOString(), now);
}

/** Resolve the zone the console should focus on: pinned, else highest priority. */
export function pickPrimaryZone(zones: Zone[] | null): Zone | null {
  if (!hasData(zones)) return null;
  return [...zones].sort((a, b) => num(b.priority_score) - num(a.priority_score))[0];
}
