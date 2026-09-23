import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
  timeout: 30000,
});

// Add auth token to requests if available
api.interceptors.request.use(
  (config) => {
    const token = typeof window !== "undefined" && localStorage.getItem("aegis_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
}

export interface ZoneListResponse {
  zones: Zone[];
  total: number;
  limit?: number;
  offset?: number;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

export interface Zone {
  zone_id: string;
  name: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_meters: number;
  priority_score: number;
  victim_count: number;
}

export interface Report {
  report_id: string;
  zone_id: string;
  source: string;
  trust_score: number;
  disaster_type: string | null;
  message_text: string | null;
  transcript: string | null;
  image_url: string | null;
  image_data: any | null;
  created_at: string;
}

export interface Resource {
  id: string;
  name: string;
  resource_type: string;
  capacity: number;
  current_load: number;
  available: boolean;
  lat: number;
  lng: number;
  zone_id: string | null;
}

export interface Incident {
  incident_id: string;
  zone_id: string;
  disaster_type: string;
  severity_score: number;
  priority_score: number;
  confidence: number;
  xai_reasoning: string;
  status: string;
  report_count: number;
  avg_trust_score: number;
  victim_count: number;
  lat: number;
  lng: number;
}

// Zone APIs
export const zonesApi = {
  list: (params?: PaginationParams) =>
    api.get<ZoneListResponse>("/api/zones", { params }),
  summary: (zone_id: string) =>
    api.get<ApiResponse<unknown>>(
      `/api/zones/${zone_id}/reports/summary`
    ),
  withPriority: (params?: PaginationParams) =>
    api.get<ZoneListResponse>(
      "/api/zones",
      { params }
    ),
};

// Incident APIs
export const incidentsApi = {
  list: (params?: { active_only?: boolean; limit?: number; zone_id?: string }) =>
    api.get<ApiResponse<{ incidents: Incident[]; total: number }>>(
      "/api/incidents",
      { params }
    ),
  get: (incident_id: string) =>
    api.get<ApiResponse<Incident>>(`/api/incidents/${incident_id}`),
  create: (data: any) => api.post("/api/incidents", data),
};

// Report APIs
export const reportsApi = {
  list: (params?: {
    zone_id?: string;
    source?: string;
    min_trust?: number;
    include_suppressed?: boolean;
    limit?: number;
    offset?: number;
  }) =>
    api.get<ApiResponse<{ reports: Report[]; total: number }>>(
      "/api/reports",
      { params }
    ),
  create: (data: any) => api.post("/api/reports", data),
  ingestText: (data: any) => api.post("/api/reports", data, { headers: { "Content-Type": "application/json" } }),
  ingestVoice: (formData: FormData) => api.post("/api/reports/voice", formData),
};

// Resource APIs
export const resourcesApi = {
  list: (params?: {
    resource_type?: string;
    zone_id?: string;
    available?: boolean;
    limit?: number;
  }) =>
    api.get<ApiResponse<{ resources: Resource[]; total: number }>>(
      "/api/resources",
      { params }
    ),
  register: (data: any) => api.post("/api/resources", data),
  assign: (incident_id: string) =>
    api.post(`/api/resources/${incident_id}/assign-resources`),
  update: (resource_id: string, available?: boolean, current_load?: number) =>
    api.put(`/api/resources/${resource_id}`, { available, current_load }),
};

// Prediction APIs
export const predictionsApi = {
  flood: (zone_id: string, hours: number = 12, rainfall_mm_hr: number = 50.0) =>
    api.post<ApiResponse<{ result: any }>>(
      "/api/predictions/flood",
      { zone_id, hours, rainfall_mm_hr }
    ),
  fire: (zone_id: string, hours: number = 12, wind_speed_kmh: number = 20.0) =>
    api.post<ApiResponse<{ result: any }>>(
      "/api/predictions/fire",
      { zone_id, hours, wind_speed_kmh }
    ),
  whatIf: (
    zone_id: string,
    disaster_type: string,
    hours: number = 12,
    rainfall_mm_hr: number = 50.0,
    wind_speed_kmh: number = 20.0,
    resource_delta: number = 0
  ) =>
    api.post<ApiResponse<{ base_prediction: any; adjusted_prediction: any }>>(
      "/api/predictions/what-if",
      { zone_id, disaster_type, hours, rainfall_mm_hr, wind_speed_kmh, resource_delta }
    ),
  getLast: (zone_id: string) =>
    api.get<ApiResponse<{ last_flood: any; last_fire: any }>>(
      `/api/predictions/${zone_id}`
    ),
};

// Command Center APIs
export const commandApi = {
  health: () => api.get<{ available: boolean; model: string }>("/api/command/health"),
  query: (data: { user_query: string; model_name?: string; conversation_id?: string }) =>
    api.post("/api/command/query", data),
  listAvailableResources: () =>
    api.get("/api/command/resources/available"),
  getZoneStatus: (zone_id: string) =>
    api.get("/api/command/zone-status", { params: { zone_id } }),
  getCriticalIncidents: (threshold: number = 70.0) =>
    api.get("/api/command/critical", { params: { threshold } }),
  getIncidentReports: (incident_id: string, limit: number = 10) =>
    api.get("/api/command/reports", { params: { incident_id, limit } }),
};

// Action APIs
export const actionsApi = {
  update: (action_id: string, status: "approved" | "rejected") =>
    api.patch(`/api/actions/${action_id}`, { status }),
  list: (params?: { incident_id?: string; status?: string }) =>
    api.get("/api/actions", { params }),
};

export default api;