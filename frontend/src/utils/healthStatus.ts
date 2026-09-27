/**
 * AEGIS-AI — Pure health status rules
 * No I/O, no React — unit-testable overall status calculation.
 */

export type ServiceStatus =
  | "ONLINE"
  | "DEGRADED"
  | "OFFLINE"
  | "UNKNOWN"
  | "REQUIRED";

export interface SystemHealth {
  api: ServiceStatus;
  database: ServiceStatus;
  auth: ServiceStatus;
  ai: ServiceStatus;
  predictions: ServiceStatus;
  maps: ServiceStatus;
  realtime: ServiceStatus;
  /** External weather provider (open-meteo) — optional, §31. */
  weather: ServiceStatus;
  /** External seismic provider (usgs) — optional, §31. */
  seismic: ServiceStatus;
  overall: ServiceStatus;
  reasons: string[];
  aiModel?: string | null;
  lastChecked?: string;
  checking: boolean;
}

export type ServiceKey =
  | "api"
  | "database"
  | "auth"
  | "ai"
  | "predictions"
  | "maps"
  | "realtime"
  | "weather"
  | "seismic";

export const SERVICE_LABELS: Record<ServiceKey, string> = {
  api: "Backend API",
  database: "Database",
  auth: "Authentication",
  ai: "NVIDIA AI",
  predictions: "Predictions",
  maps: "Mapbox",
  realtime: "Realtime",
  weather: "Weather (Open-Meteo)",
  seismic: "Seismic (USGS)",
};

/** Optional / intelligence services — failure degrades, never hard-offlines core. */
const OPTIONAL_SERVICES: ServiceKey[] = [
  "ai",
  "predictions",
  "maps",
  "realtime",
  "weather",
  "seismic",
];

export function createInitialHealth(): SystemHealth {
  return {
    api: "UNKNOWN",
    database: "UNKNOWN",
    auth: "UNKNOWN",
    ai: "UNKNOWN",
    predictions: "UNKNOWN",
    maps: "UNKNOWN",
    realtime: "UNKNOWN",
    weather: "UNKNOWN",
    seismic: "UNKNOWN",
    overall: "UNKNOWN",
    reasons: ["Checking AegisAI services…"],
    checking: true,
  };
}

/**
 * Explicit overall rules (order matters):
 * 1. Checks not finished → UNKNOWN (never show DEGRADED first)
 * 2. Core API offline → OFFLINE
 * 3. Any optional service degraded/offline → DEGRADED
 * 4. Auth REQUIRED alone does not OFFLINE the system (dashboard shows sign-in)
 * 5. Otherwise ONLINE
 */
export function calculateOverallHealth(
  health: Pick<
    SystemHealth,
    | "api"
    | "database"
    | "auth"
    | "ai"
    | "predictions"
    | "maps"
    | "realtime"
    | "weather"
    | "seismic"
    | "checking"
  >,
): ServiceStatus {
  if (health.checking) return "UNKNOWN";

  if (health.api === "OFFLINE") return "OFFLINE";

  if (health.api === "UNKNOWN" || health.ai === "UNKNOWN") return "UNKNOWN";

  for (const key of OPTIONAL_SERVICES) {
    const s = health[key];
    if (s === "DEGRADED" || s === "OFFLINE") return "DEGRADED";
  }

  if (health.api === "DEGRADED" || health.database === "DEGRADED") {
    return "DEGRADED";
  }

  // Auth required + map config incomplete → DEGRADED (not OFFLINE)
  if (health.auth === "REQUIRED" && health.maps === "DEGRADED") {
    return "DEGRADED";
  }

  return "ONLINE";
}

export function getHealthReasons(
  health: Pick<
    SystemHealth,
    | "api"
    | "database"
    | "auth"
    | "ai"
    | "predictions"
    | "maps"
    | "realtime"
    | "weather"
    | "seismic"
    | "overall"
  >,
): string[] {
  const reasons: string[] = [];

  if (health.api === "OFFLINE") {
    reasons.push("AegisAI backend is unreachable.");
    return reasons;
  }
  if (health.api === "UNKNOWN") {
    reasons.push("Checking AegisAI services…");
    return reasons;
  }

  if (health.ai === "OFFLINE" || health.ai === "DEGRADED") {
    reasons.push("NVIDIA AI unavailable. Core operational services remain online.");
  }
  if (health.predictions === "OFFLINE" || health.predictions === "DEGRADED") {
    reasons.push("Prediction service unavailable.");
  }
  if (health.maps === "OFFLINE" || health.maps === "DEGRADED") {
    reasons.push(
      "Mapbox public token is not configured for this deployment.",
    );
  }
  if (health.realtime === "OFFLINE" || health.realtime === "DEGRADED") {
    reasons.push("Live updates disconnected.");
  }
  if (health.weather === "DEGRADED" || health.weather === "OFFLINE") {
    reasons.push(
      "Weather provider degraded — forecast data may be stale (never fabricated).",
    );
  }
  if (health.seismic === "DEGRADED" || health.seismic === "OFFLINE") {
    reasons.push(
      "Seismic feed degraded — earthquake data may be stale (never fabricated).",
    );
  }
  if (health.database === "OFFLINE" || health.database === "DEGRADED") {
    reasons.push("Database degraded.");
  }
  if (health.auth === "REQUIRED") {
    reasons.push("Operator authentication required to load live operational data.");
  }

  if (reasons.length === 0) {
    if (health.overall === "ONLINE") {
      reasons.push("All core services operational.");
    } else {
      reasons.push("Some services are unavailable.");
    }
  }

  return reasons;
}

export function overallLabel(status: ServiceStatus): string {
  switch (status) {
    case "ONLINE":
      return "ONLINE";
    case "DEGRADED":
      return "DEGRADED";
    case "OFFLINE":
      return "OFFLINE";
    case "REQUIRED":
      return "REQUIRED";
    default:
      return "CHECKING";
  }
}

/** Per-row label with domain-specific wording (e.g. Mapbox config). */
export function serviceLabel(
  key: ServiceKey,
  status: ServiceStatus,
): string {
  if (key === "maps" && (status === "DEGRADED" || status === "OFFLINE")) {
    return "CONFIGURATION REQUIRED";
  }
  if (key === "auth" && status === "REQUIRED") {
    return "REQUIRED";
  }
  return overallLabel(status);
}

export function overallAriaLabel(status: ServiceStatus): string {
  return `System status: ${overallLabel(status).toLowerCase()}`;
}
