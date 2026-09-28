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
  ActionUpdateResponse,
  ApprovalQueueResponse,
  AssignResourcesResponse,
  AvailableResourcesResponse,
  CommandHealthResponse,
  CommandResponse,
  CriticalResponse,
  ExplainResponse,
  HealthResponse,
  Incident,
  IncidentListResponse,
  PredictionsResponse,
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
 * The backend currently runs in public demo mode and issues no 401, so the UI
 * never has to sign in. This exists purely so a future deployment can drop a
 * token in without touching any call site.
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
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = readToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
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

  /** Commander decision on a pending action. */
  updateAction: (
    actionId: string,
    status: "approved" | "rejected",
    note?: string,
    signal?: AbortSignal,
  ) =>
    request<ActionUpdateResponse>(`/api/actions/${encodeURIComponent(actionId)}`, {
      method: "PATCH",
      body: { status, note: note ?? null },
      signal,
    }),

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
