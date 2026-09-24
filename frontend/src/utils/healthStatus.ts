/**
 * AEGIS-AI — Pure health status rules
 * No I/O, no React — unit-testable overall status calculation.
 */

export type ServiceStatus = "ONLINE" | "DEGRADED" | "OFFLINE" | "UNKNOWN";

export interface SystemHealth {
  api: ServiceStatus;
  database: ServiceStatus;
  groq: ServiceStatus;
  predictions: ServiceStatus;
  maps: ServiceStatus;
  realtime: ServiceStatus;
  overall: ServiceStatus;
  reasons: string[];
  groqModel?: string | null;
  lastChecked?: string;
  checking: boolean;
}

export type ServiceKey =
  | "api"
  | "database"
  | "groq"
  | "predictions"
  | "maps"
  | "realtime";

export const SERVICE_LABELS: Record<ServiceKey, string> = {
  api: "API",
  database: "Database",
  groq: "Groq AI",
  predictions: "Predictions",
  maps: "Maps",
  realtime: "Realtime",
};

/** Optional / intelligence services — failure degrades, never hard-offlines core. */
const OPTIONAL_SERVICES: ServiceKey[] = [
  "groq",
  "predictions",
  "maps",
  "realtime",
];

export function createInitialHealth(): SystemHealth {
  return {
    api: "UNKNOWN",
    database: "UNKNOWN",
    groq: "UNKNOWN",
    predictions: "UNKNOWN",
    maps: "UNKNOWN",
    realtime: "UNKNOWN",
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
 * 4. Otherwise ONLINE
 */
export function calculateOverallHealth(
  health: Pick<
    SystemHealth,
    "api" | "database" | "groq" | "predictions" | "maps" | "realtime" | "checking"
  >,
): ServiceStatus {
  if (health.checking) return "UNKNOWN";

  // Core API offline wins first (Groq is marked UNKNOWN while API is down)
  if (health.api === "OFFLINE") return "OFFLINE";

  // Incomplete first check — never show DEGRADED before checks finish
  if (health.api === "UNKNOWN" || health.groq === "UNKNOWN") return "UNKNOWN";

  for (const key of OPTIONAL_SERVICES) {
    const s = health[key];
    if (s === "DEGRADED" || s === "OFFLINE") return "DEGRADED";
  }

  if (health.api === "DEGRADED" || health.database === "DEGRADED") {
    return "DEGRADED";
  }

  return "ONLINE";
}

export function getHealthReasons(
  health: Pick<SystemHealth, "api" | "database" | "groq" | "predictions" | "maps" | "realtime" | "overall">,
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

  if (health.groq === "OFFLINE" || health.groq === "DEGRADED") {
    reasons.push("Groq AI unavailable. Core operational services remain online.");
  }
  if (health.predictions === "OFFLINE" || health.predictions === "DEGRADED") {
    reasons.push("Prediction service unavailable.");
  }
  if (health.maps === "OFFLINE" || health.maps === "DEGRADED") {
    reasons.push("Map service unavailable.");
  }
  if (health.realtime === "OFFLINE" || health.realtime === "DEGRADED") {
    reasons.push("Live updates disconnected.");
  }
  if (health.database === "OFFLINE" || health.database === "DEGRADED") {
    reasons.push("Database degraded.");
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
    default:
      return "CHECKING";
  }
}

export function overallAriaLabel(status: ServiceStatus): string {
  return `System status: ${overallLabel(status).toLowerCase()}`;
}
