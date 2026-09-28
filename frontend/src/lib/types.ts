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
  bounding_box: {
    min_lat: number;
    max_lat: number;
    min_lng: number;
    max_lng: number;
  };
}
