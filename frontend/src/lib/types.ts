/**
 * Response shapes for the AegisAI backend.
 *
 * These mirror the FastAPI response models in `backend/app/api/*` one-for-one.
 * Every field the backend may omit or null out is typed as optional/nullable so
 * the UI can degrade to its existing fallbacks instead of rendering `undefined`.
 */

// ── Health ───────────────────────────────────────────────────────────────

export interface ProviderStatus {
  status: string;
  last_success_at?: string | null;
  last_error?: string | null;
  consecutive_failures?: number;
  latency_ms?: number | null;
  total_calls?: number;
  total_failures?: number;
  circuit?: string;
  detail?: string;
  canonical?: boolean;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  build: string;
  providers: Record<string, ProviderStatus>;
  services: { database: string; cache: string };
  reasons: string[];
}

export interface CommandHealthResponse {
  ai_available: boolean;
  ai_configured: boolean;
  model: string | null;
  provider: string;
  note: string;
}

// ── Zones ────────────────────────────────────────────────────────────────

export interface Zone {
  zone_id: string;
  name: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_meters: number;
  priority_score: number;
  victim_count: number;
  created_at: string | null;
}

export interface ZoneListResponse {
  zones: Zone[];
  total: number;
  limit: number;
  offset: number;
}

export interface ZoneStatusResponse {
  zone_id: string;
  zone_name: string | null;
  centroid: { lat: number | null; lng: number | null };
  incident: {
    id: string;
    priority_score: number;
    priority_band: string;
    disaster_type: string | null;
    victim_count: number;
    victim_confidence: number;
    status: string;
    report_count: number;
    avg_trust: number;
    xai_reasoning: string | null;
  } | null;
  available_resource_count: number;
}

// ── Incidents ────────────────────────────────────────────────────────────

export interface Incident {
  incident_id: string;
  zone_id: string;
  zone_name: string | null;
  lat: number | null;
  lng: number | null;
  disaster_type: string | null;
  priority_score: number;
  priority_band: string | null;
  severity_score: number | null;
  confidence: number | null;
  status: string;
  report_count: number;
  avg_trust_score: number | null;
  victim_count: number;
  victim_confidence: number;
  xai_reasoning: string | null;
  groq_summary: string | null;
  groq_explanation: string | null;
  active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface IncidentListResponse {
  incidents: Incident[];
  total: number;
  limit: number;
  offset: number;
}

export interface Report {
  report_id: string;
  zone_id: string | null;
  source: string;
  trust_score: number | null;
  suppressed: boolean;
  disaster_type: string | null;
  informative: boolean | null;
  summary: string;
  lat: number | null;
  lng: number | null;
  language_code: string | null;
  nlp_model_version: string | null;
  created_at: string | null;
}

export interface ReportListResponse {
  reports: Report[];
  total: number;
  limit: number;
  offset: number;
}

/** `POST /api/reports` — returned as soon as the report row is stored. */
export interface ReportAcceptedResponse {
  report_id: string;
  status: string;
  source: string;
  suppressed: boolean;
}

/** `POST /api/reports/voice` — transcription runs as a background task. */
export interface VoiceAcceptedResponse {
  report_id: string;
  status: string;
  source: string;
  transcript: string | null;
  stt_provider: string | null;
  message: string;
}

export interface CriticalIncident {
  incident_id: string;
  zone_id: string;
  priority_score: number;
  priority_band: string;
  disaster_type: string | null;
  victim_count: number;
  status: string;
  xai_summary: string;
}

export interface CriticalResponse {
  threshold: number;
  incidents: CriticalIncident[];
  total: number;
}

// ── Resources ────────────────────────────────────────────────────────────

export type ResourceType = "team" | "vehicle" | "supply" | "shelter";

export interface Resource {
  resource_id: string;
  name: string;
  resource_type: ResourceType;
  capacity: number;
  current_load: number;
  available: boolean;
  lat: number | null;
  lng: number | null;
  assigned_zone_id: string | null;
}

export interface ResourceListResponse {
  resources: Resource[];
  total: number;
}

export interface AvailableResource {
  id: string;
  name: string;
  resource_type: ResourceType;
  capacity: number;
  current_load: number;
  available: boolean;
  lat: number | null;
  lng: number | null;
}

export interface AvailableResourcesResponse {
  resources: AvailableResource[];
  total: number;
  availability_ratio: number;
}

// ── Predictions ──────────────────────────────────────────────────────────

export interface PredictionCell {
  lat: number;
  lng: number;
  intensity: number;
  time_step: number;
}

export interface FloodProjection {
  affected_cells: PredictionCell[];
  max_intensity: number;
  flooded_percentage: number;
  expires_at: string | null;
}

export interface FireProjection {
  burned_area: PredictionCell[];
  max_intensity: number;
  spread_direction_degrees: number;
  expires_at: string | null;
}

export interface PredictionsResponse {
  zone_id: string;
  zone_name: string;
  projection_label: string;
  last_flood: FloodProjection;
  last_fire: FireProjection;
}

/** Hazard-specific headline figures; keys vary per hazard. */
export interface HazardMetrics {
  flooded_percentage?: number;
  spread_direction_degrees?: number;
  magnitude?: number | null;
  depth_km?: number | null;
  distance_km?: number | null;
  shaking_probability?: number | null;
  susceptibility?: number | null;
  peak_rain_mm_hr?: number | null;
  mean_rain_mm_hr?: number | null;
  wind_speed_kmh?: number | null;
  impact_probability?: number | null;
}

/**
 * Long-run USGS earthquake rate for a point, from `GET /api/phase2/hazard-inventory`
 * and the `background_rate` field on an earthquake projection.
 *
 * `is_prediction` is hard-coded false on the wire and is typed as literal `false`
 * so a value of `true` fails the typecheck rather than being silently rendered as
 * if it were a forecast. This is climatology: it describes how seismically active
 * a place has been, and cannot say anything about a specific window.
 */
export interface SeismicBackgroundRate {
  source: string;
  model_id: string;
  model_version: string;
  available: boolean;
  radius_km: number;
  window_hours: number;
  min_magnitude: number;
  events_within_radius: number;
  cells_within_radius: number;
  peak_magnitude_in_history: number;
  rate_per_year: number;
  window_probability: number;
  catalogue_years: number;
  interpretation: string;
  is_prediction: false;
  limitations?: string[];
  degradation_reason?: string | null;
}

export type HazardType = "flood" | "fire" | "earthquake" | "landslide" | "storm";

/**
 * One hazard from `GET /api/predictions/all/{zone_id}`.
 *
 * `available` is authoritative: a hazard with no qualifying observation comes
 * back false with a `reason`, and its headline numbers are null or zero. That
 * covers both "no event" (earthquake all-clear) and "no current observation"
 * (a weather reading the rate-limited poller has not refreshed). Consumers must
 * check it rather than treating a zero intensity as "modelled and safe".
 */
export interface HazardProjection {
  disaster_type: HazardType;
  display_name: string;
  /** "spatially" resolves a cell grid; "zone_uniform" is a single intensity. */
  modelled: "spatially" | "zone_uniform";
  available: boolean;
  reason: string | null;
  cells: PredictionCell[];
  max_intensity: number;
  /**
   * Share of the zone affected, or null when the hazard does not model area
   * (fire). Null is not zero — 0% would claim a measurement was made.
   */
  coverage_percentage: number | null;
  metrics: HazardMetrics;
  inputs: Record<string, unknown>;
  /**
   * Earthquake only. A long-run seismic rate reported next to the live shaking
   * result, not folded into it. Absent for other hazards.
   */
  background_rate?: SeismicBackgroundRate | null;
  /** Model caveats, straight from the engine. Never hide these. */
  limitations: string[];
  expires_at: string | null;
}

export interface HazardMatrixResponse {
  zone_id: string;
  zone_name: string;
  hours_ahead: number;
  projection_label: string;
  generated_at: string;
  hazard_count: number;
  hazards: HazardProjection[];
}

/**
 * One entry from `GET /api/phase2/models`.
 *
 * `trained` is the load-bearing field: a `rules-baseline` entry with
 * `trained: false` is a deterministic function someone wrote, not a model that
 * learned anything from data. The two are presented identically in the console
 * unless this flag is respected, which would overstate the whole platform.
 */
export interface ModelRegistryEntry {
  version: string;
  runtime: string;
  trained: boolean;
  implemented_by: string;
  available?: boolean;
  trained_at?: string;
  roc_auc?: number;
  roc_auc_baseline_rule?: number;
  beats_single_feature?: boolean;
  rows?: number;
  positives?: number;
  training_data?: string;
  limitations?: string[];
  reason?: string;
  healthy?: boolean;
}

// ── Hazard inventory ─────────────────────────────────────────────────────

/** A hazard with a fitted model, keyed by hazard name. */
export interface TrainedHazardSpec {
  key: string;
  status: "trained";
  gdacs_eventtype: string | null;
  antecedent_days: number;
  feature_columns: string[];
  rule_is_shipped: boolean;
}

/** A hazard deliberately not fitted, with the reason recorded. */
export interface DeclinedHazardSpec {
  key: string;
  status: "declined";
  gdacs_eventtype: string | null;
  reason: string;
  what_would_change_it: string;
  /**
   * Present only on `seismic`: that hazard is refused as a fitted model but
   * still ships a usable background-rate artefact, so it is not a bare "no".
   */
  background_prior?: {
    available: boolean;
    model_id: string;
    model_version: string;
    is_prediction: false;
  };
}

/**
 * `GET /api/phase2/hazard-inventory`.
 *
 * The negative space matters as much as the positive: without the declined
 * rows, an absent hazard is indistinguishable from one nobody considered.
 */
export interface HazardInventoryResponse {
  engine_hazards: HazardType[];
  trained: Record<string, TrainedHazardSpec>;
  declined: Record<string, DeclinedHazardSpec>;
  trained_count: number;
  declined_count: number;
}

// ── Routes ───────────────────────────────────────────────────────────────

export interface RouteLeg {
  distance_km: number;
  estimated_minutes: number;
  note: string;
  detour_reason: string | null;
}

export interface RoutesResponse {
  zone_id: string;
  zone_name: string;
  disaster_type: string;
  blocked_roads: string[];
  primary_route: RouteLeg;
  alternate_routes: RouteLeg[];
  engine: string;
  source: string | null;
}

// ── Actions / approval queue ─────────────────────────────────────────────

export interface ApprovalAction {
  action_id: string;
  incident_id: string;
  zone_id: string | null;
  action_type: string;
  description: string;
  recommended_by: string;
  priority_score: number;
  priority_band: string;
  status: string;
  created_at: string | null;
  incident_summary: string | null;
  incident_explanation: string | null;
}

export interface ApprovalQueueResponse {
  pending_count: number;
  actions: ApprovalAction[];
  note: string;
}

export interface DecisionRecommendResponse {
  decision_id: string;
  incident_id: string;
  action_type: string;
  recommendation: string;
  confidence: number;
  evidence: Record<string, unknown>;
  explanation: string;
  model_used: string;
  model_version: string;
  requires_human_approval: boolean;
  status: string;
  created_at: string;
}

export interface DecisionApproveResponse {
  decision_id: string;
  status: string;
  message?: string;
}

export interface AssignResourcesResponse {
  incident_id: string;
  assigned_resources: unknown[];
  action_id: string;
  priority_score: number;
  message: string;
}


// ── Command center ───────────────────────────────────────────────────────

export interface FunctionCallInfo {
  name: string;
  arguments: Record<string, unknown>;
}

export interface CommandResponse {
  response: string;
  function_calls: FunctionCallInfo[];
  execution_results: Record<string, unknown>[];
  execution_time: number;
  model_used: string;
  ai_available: boolean;
  ai_configured: boolean;
  ai_call_id: string;
  conversation_id: string | null;
}

export interface ExplainResponse {
  incident_id: string;
  priority_score: number;
  priority_band: string;
  explanation: string;
  xai_raw: string | null;
  ai_used: boolean;
  evidence_attribution: EvidenceAttribution | null;
}

export interface EvidenceAttribution {
  incident_id?: string;
  sources?: Record<string, number>;
  total_evidence?: number;
  [key: string]: unknown;
}

// ── Heatmaps ─────────────────────────────────────────────────────────────

export interface HeatmapResponse {
  heatmap_type: string;
  cells: Array<Record<string, unknown>>;
  grid_size: number;
  /**
   * Null when there are no cells. An empty result is a real answer (no zones,
   * or a zone_id matching nothing), not a server error, so the map must be
   * able to render "nothing to show" instead of fitting to a zero-size box.
   */
  bounding_box: {
    min_lat: number;
    max_lat: number;
    min_lng: number;
    max_lng: number;
  } | null;
}
