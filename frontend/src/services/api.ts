/**
 * AEGIS-AI — API service layer
 * ================================
 * Axios instance with auth interceptor + typed API modules.
 *
 * SECURITY NOTE (PRD §3 / §23):
 *   - The GROQ_API_KEY lives only on the backend server.
 *   - The frontend never receives or stores the Groq key.
 *   - All LLM calls go through POST /api/command/query on the backend.
 */
import axios, { AxiosError } from "axios";

// ── Axios instance ────────────────────────────────────────────────────────

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
  timeout: 40_000,
  headers: { "Content-Type": "application/json" },
});

// Attach JWT from localStorage on every request
api.interceptors.request.use(
  (config) => {
    const token =
      typeof window !== "undefined" ? localStorage.getItem("aegis_token") : null;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (err) => Promise.reject(err),
);

export default api;

// ── Shared types ──────────────────────────────────────────────────────────

export interface Zone {
  zone_id:       string;
  name:          string;
  centroid_lat:  number;
  centroid_lng:  number;
  radius_meters: number;
  priority_score: number;
  victim_count:  number;
  deleted?:      boolean;
}

export interface Incident {
  id:              string;
  zone_id:         string;
  disaster_type:   string | null;
  severity_score:  number;
  priority_score:  number;
  priority_band:   "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  confidence:      number;
  xai_reasoning:   string | null;
  groq_summary:    string | null;
  groq_explanation: string | null;
  status:          string;
  active:          boolean;
  report_count:    number;
  avg_trust_score: number;
  victim_count:    number;
  victim_confidence: number;
  created_at:      string;
  updated_at:      string;
  lat?:            number;
  lng?:            number;
}

export interface Report {
  id:           string;
  zone_id:      string;
  source:       string;
  trust_score:  number | null;
  suppressed:   boolean;
  disaster_type: string | null;
  message_text: string | null;
  transcript:   string | null;
  lat:          number | null;
  lng:          number | null;
  created_at:   string;
}

export interface Resource {
  id:            string;
  name:          string;
  resource_type: string;
  capacity:      number;
  current_load:  number;
  available:     boolean;
  lat:           number | null;
  lng:           number | null;
  assigned_zone_id: string | null;
}

export interface Action {
  action_id:       string;
  incident_id:     string;
  zone_id:         string;
  action_type:     string;
  description:     string;
  recommended_by:  string;
  priority_score:  number;
  priority_band:   string;
  status:          string;
  created_at:      string;
}

export interface CommandResponse {
  response:          string;
  function_calls:    { name: string; arguments: Record<string, unknown> }[];
  execution_results: Record<string, unknown>[];
  execution_time:    number;
  model_used:        string;
  groq_available:    boolean;
  groq_call_id:      string;
}

export interface GroqHealthResponse {
  groq_available: boolean;
  model:          string | null;
  note:           string;
}

export interface ZoneListResponse {
  zones: Zone[];
  total: number;
}

// ── Zone APIs ─────────────────────────────────────────────────────────────

export const zonesApi = {
  list: (params?: { limit?: number; offset?: number }) =>
    api.get<ZoneListResponse>("/api/zones", { params }),

  withPriority: (params?: { limit?: number; offset?: number }) =>
    api.get<ZoneListResponse>("/api/zones", { params }),

  get: (zone_id: string) =>
    api.get<Zone>(`/api/zones/${zone_id}`),

  summary: (zone_id: string) =>
    api.get(`/api/zones/${zone_id}/reports/summary`),
};

// ── Incident APIs ─────────────────────────────────────────────────────────

export const incidentsApi = {
  list: (params?: { active_only?: boolean; limit?: number; zone_id?: string }) =>
    api.get<{ incidents: Incident[]; total: number }>("/api/incidents", { params }),

  get: (incident_id: string) =>
    api.get<Incident>(`/api/incidents/${incident_id}`),
};

// ── Report APIs ───────────────────────────────────────────────────────────

export const reportsApi = {
  list: (params?: {
    zone_id?:          string;
    source?:           string;
    min_trust?:        number;
    include_suppressed?: boolean;
    limit?:            number;
    offset?:           number;
  }) =>
    api.get<{ reports: Report[]; total: number }>("/api/reports", { params }),

  ingestText: (data: {
    message_text:    string;
    reporter_id?:    string;
    location_string?: string;
    lat?:            number;
    lng?:            number;
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
    zone_id?:       string;
    available?:     boolean;
  }) =>
    api.get<{ resources: Resource[]; total: number }>("/api/resources", { params }),

  assign: (incident_id: string) =>
    api.post(`/api/resources/${incident_id}/assign-resources`),

  update: (resource_id: string, data: { available?: boolean; current_load?: number }) =>
    api.put(`/api/resources/${resource_id}`, data),
};

// ── Prediction APIs ───────────────────────────────────────────────────────

export const predictionsApi = {
  flood: (zone_id: string, hours = 12, rainfall_mm_hr = 50) =>
    api.post("/api/predictions/flood", { zone_id, hours, rainfall_mm_hr }),

  fire: (zone_id: string, hours = 12, wind_speed_kmh = 20) =>
    api.post("/api/predictions/fire", { zone_id, hours, wind_speed_kmh }),

  whatIf: (params: {
    zone_id:        string;
    disaster_type:  string;
    hours?:         number;
    rainfall_mm_hr?: number;
    wind_speed_kmh?: number;
    resource_delta?: number;
  }) => api.post("/api/predictions/what-if", params),
};

// ── Command Center APIs ───────────────────────────────────────────────────
// The key to remember: none of these endpoints expose GROQ_API_KEY.
// All LLM work happens inside the backend.

export const commandApi = {
  /** Check whether Groq AI Gateway is configured on the backend. */
  health: () => api.get<GroqHealthResponse>("/api/command/health"),

  /**
   * Send a natural-language query to the Groq AI Gateway.
   * The backend handles the key; the browser only sends text.
   */
  query: (data: {
    user_query:      string;
    model_name?:     string;
    conversation_id?: string;
    include_xai?:    boolean;
    zone_context?:   string;
  }) => api.post<CommandResponse>("/api/command/query", data),

  /** Plain-English explanation of an incident's XAI evidence. */
  explain: (incident_id: string) =>
    api.get<{
      incident_id:   string;
      priority_score: number;
      priority_band: string;
      explanation:   string;
      xai_raw:       string;
      groq_used:     boolean;
    }>(`/api/command/explain/${incident_id}`),

  /** Concise operational summary for a commander briefing. */
  summarise: (incident_id: string) =>
    api.get<{
      incident_id: string;
      summary:     string;
      evidence:    Record<string, unknown>;
      groq_used:   boolean;
    }>(`/api/command/summarise/${incident_id}`),

  /** List all available resources — deterministic, no LLM. */
  listAvailableResources: () =>
    api.get<{ resources: Resource[]; total: number; availability_ratio: number }>(
      "/api/command/resources/available",
    ),

  /** Comprehensive zone status — deterministic. */
  zoneStatus: (zone_id: string) =>
    api.get("/api/command/zone-status", { params: { zone_id } }),

  /** Incidents above a priority threshold — deterministic. */
  critical: (threshold = 70, limit = 10) =>
    api.get<{ incidents: Incident[]; total: number; threshold: number }>(
      "/api/command/critical",
      { params: { threshold, limit } },
    ),

  /** Recent reports for an incident — deterministic. */
  reports: (incident_id: string, limit = 10) =>
    api.get<{ reports: Report[]; total: number }>(
      "/api/command/reports",
      { params: { incident_id, limit } },
    ),

  /**
   * Actions pending human approval.
   * PRD §9: Only a human commander can approve these. The LLM cannot.
   */
  approvalQueue: () =>
    api.get<{
      pending_count: number;
      actions:       Action[];
      note:          string;
    }>("/api/command/approval-queue"),
};

// ── Action APIs ───────────────────────────────────────────────────────────

export const actionsApi = {
  /** Approve or reject a pending action — commander only. */
  updateStatus: (action_id: string, status: "approved" | "rejected", note?: string) =>
    api.patch(`/api/actions/${action_id}`, { status, note }),

  list: (params?: { incident_id?: string; status?: string; zone_id?: string }) =>
    api.get<{ actions: Action[] }>("/api/actions", { params }),
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
