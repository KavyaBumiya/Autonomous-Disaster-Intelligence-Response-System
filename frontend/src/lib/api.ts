/**
 * Thin fetch wrapper around the AegisAI REST API.
 *
 * Design rules, in priority order:
 *  1. The backend origin is configuration, never a literal — see `config.ts`.
 *  2. A failing backend must never throw into a React render. Callers decide
 *     how to degrade; this module only reports the failure faithfully.
 *  3. Every request is abortable and time-boxed so a stalled backend cannot
 *     leave a panel spinning forever.
 */
import {
  API_BASE,
  COMMAND_TIMEOUT_MS,
  REQUEST_TIMEOUT_MS,
  apiUrl,
} from "./config";
import type {
  ApprovalQueueResponse,
  AssignResourcesResponse,
  AvailableResourcesResponse,
  CommandHealthResponse,
  CommandResponse,
  DecisionApproveResponse,
  DecisionRecommendResponse,
  CriticalResponse,
  ExplainResponse,
  HealthResponse,
  Incident,
  IncidentListResponse,
  PredictionsResponse,
  ReportListResponse,
  Resource,
  ResourceListResponse,
  ResourceType,
  RoutesResponse,
  ZoneListResponse,
  ZoneStatusResponse,
} from "./types";

/** Error carrying the HTTP status and FastAPI `detail` so callers can branch. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** True for failures that mean "no data", not "backend is broken". */
  get isNotFound(): boolean {
    return this.status === 404;
  }
}

/** True when the request never reached a healthy backend. */
export function isNetworkError(error: unknown): boolean {
  return (
    error instanceof ApiError
      ? false
      : error instanceof TypeError || error instanceof DOMException
  );
}

type TokenReader = () => string | null;

let readToken: TokenReader = () => null;

/**
 * Optional bearer-token hook.
 *
 * This deployment runs unauthenticated: the backend issues no 401, so the UI
 * never has to sign in. The hook exists so a future deployment can drop a token
 * in without touching any call site.
 */
export function setAuthTokenReader(reader: TokenReader | null): void {
  readToken = reader ?? (() => null);
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/** Combine a caller signal with a timeout into a single abort signal. */
function withTimeout(
  timeoutMs: number,
  callerSignal?: AbortSignal,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const onCallerAbort = () => controller.abort();
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener("abort", onCallerAbort);
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    },
  };
}

/** Pull a human-readable message out of a FastAPI error body. */
function extractDetail(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  return fallback;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, signal, timeoutMs = REQUEST_TIMEOUT_MS } = options;
  const { signal: effectiveSignal, cleanup } = withTimeout(timeoutMs, signal);

  const headers: Record<string, string> = { Accept: "application/json" };
  const isFormDataBody = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isFormDataBody) headers["Content-Type"] = "application/json";
  const token = readToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : isFormDataBody ? body as FormData : JSON.stringify(body),
      signal: effectiveSignal,
      mode: "cors",
      credentials: "omit",
    });

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        detail = extractDetail(await response.json(), detail);
      } catch {
        // Non-JSON error body — keep the status line.
      }
      throw new ApiError(response.status, detail);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, `Request timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    cleanup();
  }
}

/** Build a query string, dropping empty/zero values so the URL stays clean. */
function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  // ── Health ──────────────────────────────────────────────────────────────
  health: (signal?: AbortSignal) =>
    request<HealthResponse>("/api/health", { signal }),

  commandHealth: (signal?: AbortSignal) =>
    request<CommandHealthResponse>("/api/command/health", { signal, timeoutMs: 12_000 }),

  // ── Zones ───────────────────────────────────────────────────────────────
  zones: (signal?: AbortSignal) =>
    request<ZoneListResponse>(`/api/zones${query({ limit: 100 })}`, { signal }),

  zoneStatus: (zoneId: string, signal?: AbortSignal) =>
    request<ZoneStatusResponse>(`/api/command/zone-status${query({ zone_id: zoneId })}`, { signal }),

  // ── Incidents ───────────────────────────────────────────────────────────
  incidents: (
    params: { activeOnly?: boolean; zoneId?: string; limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    request<IncidentListResponse>(
      `/api/incidents${query({
        active_only: params.activeOnly ?? true,
        zone_id: params.zoneId,
        limit: params.limit ?? 50,
      })}`,
      { signal },
    ),

  incident: (incidentId: string, signal?: AbortSignal) =>
    request<Incident>(`/api/incidents/${encodeURIComponent(incidentId)}`, { signal }),

  reports: (
    params: { zoneId?: string; limit?: number; minTrust?: number } = {},
    signal?: AbortSignal,
  ) =>
    request<ReportListResponse>(
      `/api/reports${query({ zone_id: params.zoneId, limit: params.limit ?? 100, min_trust: params.minTrust ?? 0.25 })}`,
      { signal },
    ),

  critical: (threshold = 70, limit = 10, signal?: AbortSignal) =>
    request<CriticalResponse>(`/api/command/critical${query({ threshold, limit })}`, { signal }),

  explain: (incidentId: string, signal?: AbortSignal) =>
    request<ExplainResponse>(`/api/command/explain/${encodeURIComponent(incidentId)}`, {
      signal,
      timeoutMs: COMMAND_TIMEOUT_MS,
    }),

  // ── Resources ───────────────────────────────────────────────────────────
  resources: (
    params: { resourceType?: ResourceType; zoneId?: string; available?: boolean } = {},
    signal?: AbortSignal,
  ) =>
    request<ResourceListResponse>(
      `/api/resources${query({
        resource_type: params.resourceType,
        zone_id: params.zoneId,
        available: params.available,
      })}`,
      { signal },
    ),

  registerResource: (body: {
    name: string;
    resource_type: ResourceType;
    capacity?: number;
    lat?: number | null;
    lng?: number | null;
  }, signal?: AbortSignal) => {
    const form = new FormData();
    form.set("name", body.name);
    form.set("resource_type", body.resource_type);
    form.set("capacity", String(body.capacity ?? 1));
    if (body.lat !== undefined && body.lat !== null) form.set("lat", String(body.lat));
    if (body.lng !== undefined && body.lng !== null) form.set("lng", String(body.lng));
    return request<Resource>("/api/resources", { method: "POST", body: form, signal });
  },

  availableResources: (signal?: AbortSignal) =>
    request<AvailableResourcesResponse>("/api/command/resources/available", { signal }),

  /**
   * Run the deterministic resource commander for an incident. The backend
   * assigns available resources and creates a pending action for the human
   * approval gate — it does not authorise dispatch.
   */
  assignResources: (incidentId: string, signal?: AbortSignal) =>
    request<AssignResourcesResponse>(
      `/api/resources/${encodeURIComponent(incidentId)}/assign-resources`,
      { method: "POST", signal, timeoutMs: 45_000 },
    ),



  // ── Predictions & routes ────────────────────────────────────────────────
  predictions: (zoneId: string, signal?: AbortSignal) =>
    request<PredictionsResponse>(`/api/predictions/${encodeURIComponent(zoneId)}`, {
      signal,
      timeoutMs: 45_000,
    }),

  computeRoutes: (
    body: {
      zone_id: string;
      blocked_roads?: string;
      disaster_type?: string;
      origin_lat?: number | null;
      origin_lng?: number | null;
    },
    signal?: AbortSignal,
  ) =>
    request<RoutesResponse>("/api/routes/compute", {
      method: "POST",
      body,
      signal,
      timeoutMs: 45_000,
    }),

  // ── Decision & approval ────────────────────────────────────────────────
  decisionRecommend: (body: {
    incident_id: string;
    action_type: "evacuation" | "dispatch" | "resource_allocation" | "emergency_communication" | "rescue";
    context?: Record<string, unknown>;
    hazard_type?: string | null;
    location?: { lat?: number | null; lng?: number | null } | null;
  }, signal?: AbortSignal) =>
    request<DecisionRecommendResponse>("/api/decision/recommend", {
      method: "POST",
      body,
      signal,
      timeoutMs: COMMAND_TIMEOUT_MS,
    }),

  decisionApprove: (decisionId: string, note?: string, signal?: AbortSignal) =>
    request<DecisionApproveResponse>("/api/decision/approve", {
      method: "POST",
      body: { decision_id: decisionId, note: note ?? null },
      signal,
      timeoutMs: REQUEST_TIMEOUT_MS,
    }),

  decisionReject: (decisionId: string, reason: string, signal?: AbortSignal) =>
    request<DecisionApproveResponse>("/api/decision/reject", {
      method: "POST",
      body: { decision_id: decisionId, reason },
      signal,
      timeoutMs: REQUEST_TIMEOUT_MS,
    }),

  // ── Command center ──────────────────────────────────────────────────────
  approvalQueue: (signal?: AbortSignal) =>
    request<ApprovalQueueResponse>("/api/command/approval-queue", { signal }),

  commandQuery: (
    body: {
      user_query: string;
      conversation_id?: string | null;
      include_xai?: boolean;
      zone_context?: string | null;
      model_name?: string | null;
    },
    signal?: AbortSignal,
  ) =>
    request<CommandResponse>("/api/command/query", {
      method: "POST",
      body,
      signal,
      timeoutMs: COMMAND_TIMEOUT_MS,
    }),
};

/** Absolute origin string for diagnostics/debugging surfaces. */
export const apiOrigin = API_BASE || "(same origin)";
