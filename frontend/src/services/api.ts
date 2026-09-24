/**
 * AEGIS-AI — API service layer
 * ================================
 * Axios instance with auth interceptor + typed API modules.
 *
 * SECURITY NOTE (PRD §3 / §23):
 *   - The GROQ_API_KEY lives only on the backend server.
 *   - The frontend never receives or stores the Groq key.
 *   - All LLM calls go through POST /api/command/query on the backend.
 *
 * Transport:
 *   - Default baseURL is relative ("/") so the Vite proxy (dev) and nginx
 *     (prod) forward /api and /socket.io to the backend.
 *   - VITE_API_BASE_URL can override when frontend/backend are on different
 *     origins.
 */
import axios, { AxiosError } from "axios";

// ── Axios instance ────────────────────────────────────────────────────────

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/",
  timeout: 40_000,
  headers: { "Content-Type": "application/json" },
});

const TOKEN_KEY = "aegis_token";
const ROLE_KEY = "aegis_role";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ROLE_KEY);
}

export function setAuth(token: string, role: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(ROLE_KEY, role);
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}

// Attach JWT from localStorage on every request
api.interceptors.request.use(
  (config) => {
    const token = getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (err) => Promise.reject(err),
);

// On 401, clear stale token so bootstrap can re-login
api.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      clearAuth();
    }
    return Promise.reject(err);
  },
);

export default api;

// ── Auth ──────────────────────────────────────────────────────────────────

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
  expires_in: number;
}

export const authApi = {
  login: (username: string, password: string) =>
    api.post<LoginResponse>("/api/auth/login", { username, password }),

  me: () => api.get<{ user_id: string; role: string }>("/api/auth/me"),
};

/**
 * Ensure a valid JWT exists. Called once at app bootstrap.
 * Uses demo commander credentials (seeded by backend/seed.py).
 */
export async function ensureAuth(): Promise<void> {
  if (getToken()) return;
  try {
    const res = await authApi.login("commander@aegis.demo", "demo123");
    setAuth(res.data.access_token, res.data.role);
  } catch (err) {
    console.error("Auth bootstrap failed (is the backend up?)", err);
  }
}

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
  groq_available: boolean;
  groq_call_id: string;
  conversation_id?: string | null;
}

export interface GroqHealthResponse {
  groq_available: boolean;
  model: string | null;
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
};

// ── Route APIs ────────────────────────────────────────────────────────────

export const routesApi = {
  compute: (params: {
    zone_id: string;
    blocked_roads?: string;
    disaster_type?: string;
  }) => api.post<RoutesResult>("/api/routes/compute", params),
};

// ── Heatmap APIs ──────────────────────────────────────────────────────────

export const heatmapsApi = {
  combined: (zone_id?: string) =>
    api.get("/api/heatmaps/combined", {
      params: zone_id ? { zone_id } : undefined,
    }),
};

// ── Command Center APIs ───────────────────────────────────────────────────
// The key to remember: none of these endpoints expose GROQ_API_KEY.
// All LLM work happens inside the backend.

export const commandApi = {
  health: () => api.get<GroqHealthResponse>("/api/command/health"),

  query: (data: {
    user_query: string;
    model_name?: string;
    conversation_id?: string;
    include_xai?: boolean;
    zone_context?: string;
  }) => api.post<CommandResponse>("/api/command/query", data),

  explain: (incident_id: string) =>
    api.get<{
      incident_id: string;
      priority_score: number;
      priority_band: string;
      explanation: string;
      xai_raw: string;
      groq_used: boolean;
    }>(`/api/command/explain/${incident_id}`),

  summarise: (incident_id: string) =>
    api.get<{
      incident_id: string;
      summary: string;
      evidence: Record<string, unknown>;
      groq_used: boolean;
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
