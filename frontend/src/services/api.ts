/**
 * AEGIS-AI — API service layer
 * ================================
 * Axios instance + typed API modules.
 *
 * Public demo mode (2026-09): sign-in was removed. The backend serves every
 * route without a token, so the frontend attaches no Authorization header
 * and performs no auth bootstrap before first paint.
 *
 * SECURITY NOTE (PRD §3 / §23):
 *   - The NVIDIA_API_KEY lives only on the backend server.
 *   - The frontend never receives or stores the NVIDIA NIM key.
 *   - All LLM calls go through POST /api/command/query on the backend.
 *
 * Transport:
 *   - Default baseURL is relative ("/") so the Vite proxy (dev) and nginx
 *     (prod) forward /api and /socket.io to the backend.
 *   - VITE_API_BASE_URL can override when frontend/backend are on different
 *     origins.
 */
import axios, { type AxiosError } from "axios";

// ── Axios instance ────────────────────────────────────────────────────────

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/",
  timeout: 40_000,
  headers: { "Content-Type": "application/json" },
});

export default api;

// ── Shared types ──────────────────────────────────────────────────────────

export interface Zone {
  zone_id: string;
  name: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_meters: number;
  priority_score: number;
  victim_count: number;
  deleted?: boolean;
}

export interface Incident {
  incident_id: string;
  zone_id: string;
  zone_name?: string | null;
  disaster_type: string | null;
  severity_score: number;
  priority_score: number;
  priority_band?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  confidence: number;
  xai_reasoning: string | null;
  /**
   * Legacy field names. These are the actual wire contract from
   * GET /api/incidents: the backend still reads/writes the pre-migration
   * `Incident.groq_summary` / `Incident.groq_explanation` database columns.
   * Only the JSON keys are stale; the content is now NVIDIA NIM output.
   * A follow-up DB migration will rename the columns and these fields.
   */
  groq_summary: string | null;
  groq_explanation: string | null;
  status: string;
  active: boolean;
  report_count: number;
  avg_trust_score: number;
  victim_count: number;
  victim_confidence: number;
  created_at: string;
  updated_at?: string | null;
  lat?: number | null;
  lng?: number | null;
}

export interface Report {
  /** Primary key from /api/reports list endpoint */
  report_id?: string;
  /** Alternate key used by command center /api/command/reports */
  id?: string;
  zone_id?: string;
  source?: string;
  trust_score?: number | null;
  suppressed?: boolean;
  disaster_type?: string | null;
  summary?: string | null;
  message_text?: string | null;
  transcript?: string | null;
  excerpt?: string | null;
  lat?: number | null;
  lng?: number | null;
  created_at?: string | null;
}

export interface Resource {
  resource_id: string;
  name: string;
  resource_type: string;
  capacity: number;
  current_load: number;
  available: boolean;
  lat: number | null;
  lng: number | null;
  assigned_zone_id: string | null;
}

export interface Action {
  action_id: string;
  incident_id: string;
  zone_id: string;
  action_type: string;
  description: string;
  recommended_by: string;
  priority_score: number;
  priority_band: string;
  status: string;
  created_at: string;
  incident_summary?: string | null;
  incident_explanation?: string | null;
}

export interface CommandResponse {
  response: string;
  function_calls: { name: string; arguments: Record<string, unknown> }[];
  execution_results: Record<string, unknown>[];
  execution_time: number;
  model_used: string;
  /** True only when the NIM model produced `response`; False on any fallback. */
  ai_available: boolean;
  /** True when a key is present in the server env, even if it fails to authenticate. */
  ai_configured?: boolean;
  ai_call_id: string;
  conversation_id?: string | null;
}

export interface AIHealthResponse {
  /** True only when a live NIM probe succeeded, not merely when a key exists. */
  ai_available: boolean;
  /** A key is present in the server env, even if it fails to authenticate. */
  ai_configured: boolean;
  model: string | null;
  provider: string;
  note: string;
}

export interface ZoneListResponse {
  zones: Zone[];
  total: number;
}

export interface RouteEstimate {
  distance_km: number;
  estimated_minutes: number;
  note?: string;
  detour_reason?: string | null;
}

export interface RoutesResult {
  zone_id: string;
  zone_name?: string;
  disaster_type: string;
  blocked_roads: string[];
  primary_route: RouteEstimate;
  alternate_routes: RouteEstimate[];
  engine?: string;
  // Additive Phase 5 fields
  source?: string;
  /**
   * Plain [lng, lat] pairs, NOT a GeoJSON LineString. The backend serialises
   * the route centreline as a bare array; typing it as GeoJSON previously
   * forced every consumer to special-case it.
   */
  geometry?: [number, number][] | null;
  cost?: number;
  penalties?: Record<string, number>;
}

// ── Weather types (Phase 15) ──────────────────────────────────────────────

export interface WeatherCurrent {
  provider: string;
  lat: number;
  lng: number;
  rainfall_mm_hr: number;
  wind_speed_kmh: number;
  temperature_c: number | null;
  humidity_pct: number | null;
  weather_main: string;
  weather_description: string;
  risk_score: number;
  timestamp: string;
  from_cache: boolean;
  source: "current";
}

export interface ForecastSlice {
  time: string;
  precipitation_mm: number;
  precipitation_probability_pct: number | null;
  temperature_c: number | null;
}

export interface WeatherForecast {
  provider: string;
  lat: number;
  lng: number;
  hours: ForecastSlice[];
  retrieved_at: string | null;
  from_cache: boolean;
  source: "forecast";
}

// ── Seismic types (Phase 15) ──────────────────────────────────────────────

export interface EarthquakeEvent {
  id?: string;
  usgs_id?: string;
  magnitude: number;
  depth_km: number | null;
  lat: number;
  lng: number;
  place_description?: string | null;
  place?: string | null;
  event_time: string;
  risk_score: number;
}

export interface EarthquakeListResponse {
  earthquakes: EarthquakeEvent[];
  total: number;
  window_minutes: number;
  source?: string;
}

// ── Evidence attribution (Phase 13/15, §33) ───────────────────────────────

export interface EvidenceAttribution {
  source: string;
  observation_type: string | null;
  provider: string;
  confidence: number;
  retrieved_at: string | null;
  available: boolean;
  reason?: string | null;
}

export interface ExplainResponse {
  incident_id: string;
  priority_score: number;
  priority_band: string;
  explanation: string;
  xai_raw: string;
  ai_used: boolean;
  evidence_attribution: EvidenceAttribution[];
}

// ── Prediction types ──────────────────────────────────────────────────────

/** Grid cell emitted by the prediction engine. Points, not polygons. */
export interface PredictionCell {
  lat: number;
  lng: number;
  intensity: number;
  time_step: number;
}

export interface FloodPredictionResult {
  affected_cells: PredictionCell[];
  max_intensity: number;
  flooded_percentage: number;
  expires_at: string | null;
  projection_label?: string;
  disaster_type?: string;
  generated_at?: string;
}

export interface FirePredictionResult {
  burned_area: PredictionCell[];
  max_intensity: number;
  spread_direction_degrees: number;
  expires_at: string | null;
  projection_label?: string;
  disaster_type?: string;
  generated_at?: string;
}

/** GET /api/predictions/{zone_id} — both runs are computed live per request. */
export interface ZonePredictionResponse {
  zone_id: string;
  zone_name?: string | null;
  projection_label?: string;
  last_flood: FloodPredictionResult | null;
  last_fire: FirePredictionResult | null;
}

/** Per-zone row from the heatmap endpoints. */
export interface HeatmapCell {
  grid_id?: string;
  zone_id: string;
  zone_name?: string | null;
  centroid_lat: number;
  centroid_lng: number;
  victim_count?: number;
  area_km2?: number | null;
  victim_density?: number | null;
  disaster_type?: string | null;
}

export interface HeatmapResponse {
  heatmap_type: string;
  cells: HeatmapCell[];
  grid_size: number;
  bounding_box?: {
    min_lat: number;
    max_lat: number;
    min_lng: number;
    max_lng: number;
  } | null;
}

// ── Zone APIs ─────────────────────────────────────────────────────────────

export const zonesApi = {
  list: (params?: { limit?: number; offset?: number }) =>
    api.get<ZoneListResponse>("/api/zones", { params }),

  withPriority: (params?: { limit?: number; offset?: number }) =>
    api.get<ZoneListResponse>("/api/zones", { params }),

  get: (zone_id: string) => api.get<Zone>(`/api/zones/${zone_id}`),

  summary: (zone_id: string) =>
    api.get(`/api/zones/${zone_id}/reports/summary`),
};

// ── Incident APIs ─────────────────────────────────────────────────────────

export const incidentsApi = {
  list: (params?: {
    active_only?: boolean;
    limit?: number;
    zone_id?: string;
  }) =>
    api.get<{ incidents: Incident[]; total: number }>("/api/incidents", {
      params,
    }),

  get: (incident_id: string) =>
    api.get<Incident>(`/api/incidents/${incident_id}`),
};

// ── Report APIs ───────────────────────────────────────────────────────────

export const reportsApi = {
  list: (params?: {
    zone_id?: string;
    source?: string;
    min_trust?: number;
    include_suppressed?: boolean;
    limit?: number;
    offset?: number;
  }) =>
    api.get<{ reports: Report[]; total: number }>("/api/reports", { params }),

  ingestText: (data: {
    message_text: string;
    reporter_id?: string;
    location_string?: string;
    lat?: number;
    lng?: number;
  }) => api.post("/api/reports", data),

  ingestVoice: (formData: FormData) =>
    api.post("/api/reports/voice", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    }),
};

// ── Resource APIs ─────────────────────────────────────────────────────────

export const resourcesApi = {
  list: (params?: {
    resource_type?: string;
    zone_id?: string;
    available?: boolean;
  }) =>
    api.get<{ resources: Resource[]; total: number }>("/api/resources", {
      params,
    }),

  assign: (incident_id: string) =>
    api.post(`/api/resources/${incident_id}/assign-resources`),

  update: (
    resource_id: string,
    data: { available?: boolean; current_load?: number },
  ) => api.put(`/api/resources/${resource_id}`, data),
};

// ── Prediction APIs ───────────────────────────────────────────────────────

export const predictionsApi = {
  flood: (zone_id: string, hours = 12, rainfall_mm_hr = 50) =>
    api.post("/api/predictions/flood", { zone_id, hours, rainfall_mm_hr }),

  fire: (zone_id: string, hours = 12, wind_speed_kmh = 20) =>
    api.post("/api/predictions/fire", { zone_id, hours, wind_speed_kmh }),

  whatIf: (params: {
    zone_id: string;
    disaster_type: string;
    hours?: number;
    rainfall_mm_hr?: number;
    wind_speed_kmh?: number;
    resource_delta?: number;
  }) => api.post("/api/predictions/what-if", params),

  /**
   * Latest flood + fire projection for one zone.
   *
   * The engine runs live on every call (12h horizon, latest weather reading,
   * current evidence and GIS context), so callers should cache this per zone
   * rather than refetching on a tight interval. 404 when the zone is unknown.
   */
  forZone: (zone_id: string) =>
    api.get<ZonePredictionResponse>(`/api/predictions/${zone_id}`),
};

// ── Route APIs ────────────────────────────────────────────────────────────

export const routesApi = {
  compute: (params: {
    zone_id: string;
    blocked_roads?: string;
    disaster_type?: string;
  }) => api.post<RoutesResult>("/api/routes/compute", params),
};

// ── Weather APIs (Phase 15 — backend-owned Open-Meteo) ────────────────────

export const weatherApi = {
  current: (lat: number, lng: number) =>
    api.get<WeatherCurrent>("/api/weather/current", { params: { lat, lng } }),

  forecast: (lat: number, lng: number, hours = 24) =>
    api.get<WeatherForecast>("/api/weather/forecast", {
      params: { lat, lng, hours },
    }),
};

// ── Earthquake APIs (Phase 15 — local USGS poll) ──────────────────────────

export const earthquakesApi = {
  recent: (params?: { minutes?: number; min_magnitude?: number; limit?: number }) =>
    api.get<EarthquakeListResponse>("/api/earthquakes/recent", { params }),
};

// ── Heatmap APIs ──────────────────────────────────────────────────────────

export const heatmapsApi = {
  // Left untyped on purpose: DashboardLayout and HeatmapsPage consume this
  // through their own looser HeatmapPayload shape, which has an index
  // signature the narrower HeatmapResponse does not satisfy.
  combined: (zone_id?: string) =>
    api.get("/api/heatmaps/combined", {
      params: zone_id ? { zone_id } : undefined,
    }),

  /**
   * Per-zone victim density. Unauthenticated on the backend.
   *
   * Known backend bug: `cells[].victim_count` is currently computed as
   * COUNT(Incident.id) — a count of incidents, not of people. The real victim
   * number is only used as the density denominator, so treat the count as an
   * incident tally and prefer `victim_density` for magnitude.
   */
  victimDensity: (zone_id?: string) =>
    api.get<HeatmapResponse>("/api/heatmaps/victim-density", {
      params: zone_id ? { zone_id } : undefined,
    }),
};

// ── Command Center APIs ───────────────────────────────────────────────────
// The key to remember: none of these endpoints expose NVIDIA_API_KEY.
// All LLM work happens inside the backend.

export const commandApi = {
  health: () => api.get<AIHealthResponse>("/api/command/health"),

  query: (data: {
    user_query: string;
    model_name?: string;
    conversation_id?: string;
    include_xai?: boolean;
    zone_context?: string;
  }) => api.post<CommandResponse>("/api/command/query", data),

  explain: (incident_id: string) =>
    api.get<ExplainResponse>(`/api/command/explain/${incident_id}`),

  summarise: (incident_id: string) =>
    api.get<{
      incident_id: string;
      summary: string;
      evidence: Record<string, unknown>;
      ai_used: boolean;
    }>(`/api/command/summarise/${incident_id}`),

  listAvailableResources: () =>
    api.get<{ resources: Resource[]; total: number; availability_ratio: number }>(
      "/api/command/resources/available",
    ),

  zoneStatus: (zone_id: string) =>
    api.get("/api/command/zone-status", { params: { zone_id } }),

  critical: (threshold = 70, limit = 10) =>
    api.get<{ incidents: Incident[]; total: number; threshold: number }>(
      "/api/command/critical",
      { params: { threshold, limit } },
    ),

  reports: (incident_id: string, limit = 10) =>
    api.get<{ reports: Report[]; total: number }>("/api/command/reports", {
      params: { incident_id, limit },
    }),

  approvalQueue: () =>
    api.get<{
      pending_count: number;
      actions: Action[];
      note: string;
    }>("/api/command/approval-queue"),
};

// ── Action APIs ───────────────────────────────────────────────────────────

export const actionsApi = {
  updateStatus: (
    action_id: string,
    status: "approved" | "rejected",
    note?: string,
  ) => api.patch(`/api/actions/${action_id}`, { status, note }),
};

// ── Google Maps APIs ──────────────────────────────────────────────────────

export const mapsApi = {
  geocode: (address: string) =>
    api.get("/api/maps/geocode", { params: { address } }),

  reverseGeocode: (lat: number, lng: number) =>
    api.get("/api/maps/reverse-geocode", { params: { lat, lng } }),

  placesNearby: (lat: number, lng: number, radius = 500, keyword?: string, placeType?: string) =>
    api.get("/api/maps/places", { params: { lat, lng, radius, keyword, place_type: placeType } }),
};

// ── OpenAI APIs ───────────────────────────────────────────────────────────

export const openaiApi = {
  analyzeDisaster: (context: Record<string, unknown>, analysisType = "situational_awareness") =>
    api.post("/api/openai/analyze-disaster", { context, analysis_type: analysisType }),

  chat: (messages: Array<{ role: string; content: string }>, model = "gpt-4o-mini") =>
    api.post("/api/openai/chat", { messages, model }),
};

// ── NASA FIRMS APIs ───────────────────────────────────────────────────────

export const firmsApi = {
  activeFires: (lat: number, lng: number, radiusKm = 500, days = 7) =>
    api.get("/api/firms/fires", { params: { lat, lng, radius_km: radiusKm, days } }),

  globalFires: (source = "VIIRS_SNPP_NRT", dayRange = 1) =>
    api.get("/api/firms/fires/global", { params: { source, day_range: dayRange } }),
};

// ── TomTom APIs ───────────────────────────────────────────────────────────

export const trafficApi = {
  route: (originLat: number, originLng: number, destLat: number, destLng: number, traffic = true) =>
    api.get("/api/traffic/route", { params: { origin_lat: originLat, origin_lng: originLng, dest_lat: destLat, dest_lng: destLng, traffic } }),

  flow: (lat: number, lng: number, zoom = 10) =>
    api.get("/api/traffic/flow", { params: { lat, lng, zoom } }),

  search: (q: string, lat?: number, lng?: number, limit = 10) =>
    api.get("/api/traffic/search", { params: { q, lat, lng, limit } }),
};

// ── Cesium Ion APIs ──────────────────────────────────────────────────────

export const globeApi = {
  token: () => api.get<{ accessToken: string; assetId: number | null }>("/api/globe/token"),

  asset: (assetId: number) => api.get(`/api/globe/assets/${assetId}`),

  assets: (assetType = "IMAGERY") =>
    api.get("/api/globe/assets", { params: { asset_type: assetType } }),
};

// ── Utility ───────────────────────────────────────────────────────────────

/** Extracts a readable error message from any Axios error. */
export function apiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const e = err as AxiosError<{ detail?: string; message?: string }>;
    return (
      e.response?.data?.detail ||
      e.response?.data?.message ||
      e.message ||
      "Unknown API error"
    );
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
