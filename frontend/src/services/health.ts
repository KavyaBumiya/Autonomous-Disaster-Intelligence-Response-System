/**
 * AEGIS-AI — Health check service
 * Separate endpoints for separate concerns:
 *   - GET /api/health           → core backend/API liveness
 *   - GET /api/command/health   → NVIDIA NIM AI Gateway configuration
 * Never collapse these into one boolean.
 */
import api, { type AIHealthResponse } from "./api";

export interface ProviderStatus {
  status: string;
  last_success_at?: number | null;
  last_error?: string | null;
  consecutive_failures?: number;
  latency_ms?: number | null;
  total_calls?: number;
  total_failures?: number;
}

export interface ApiHealthResponse {
  status: string;
  version?: string;
  /** Additive (§31): external provider status from the backend registry. */
  providers?: Record<string, ProviderStatus>;
}

export type HealthCheckResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; code?: number };

/** Core application health — NOT the NVIDIA/command health endpoint. */
export async function getApiHealth(): Promise<HealthCheckResult<ApiHealthResponse>> {
  try {
    const res = await api.get<ApiHealthResponse>("/api/health", { timeout: 8000 });
    return { ok: true, data: res.data };
  } catch (err) {
    return { ok: false, error: classifyHealthError(err) };
  }
}

/** NVIDIA / Command Center health only. */
export async function getCommandHealth(): Promise<HealthCheckResult<AIHealthResponse>> {
  try {
    const res = await api.get<AIHealthResponse>("/api/command/health", { timeout: 8000 });
    return { ok: true, data: res.data };
  } catch (err) {
    return { ok: false, error: classifyHealthError(err) };
  }
}

export function classifyHealthError(err: unknown): string {
  const e = err as {
    response?: { status?: number };
    code?: string;
    message?: string;
  };
  if (!e.response) {
    return "Backend/network unreachable";
  }
  const status = e.response.status;
  switch (status) {
    case 401:
      return "Authentication issue";
    case 403:
      return "Permission issue";
    case 404:
      return "Endpoint not found";
    case 422:
      return "Validation issue";
    case 429:
      return "Rate limit";
    case 500:
      return "Server error";
    case 503:
      return "Service unavailable";
    default:
      return e.message || `HTTP ${status ?? "error"}`;
  }
}
