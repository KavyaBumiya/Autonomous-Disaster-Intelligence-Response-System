/**
 * AEGIS-AI — Shared system health store (zustand)
 * One poller for all badge/detail consumers. No per-component health logic.
 */
import { create } from "zustand";
import { getApiHealth, getCommandHealth } from "@/services/health";
import {
  calculateOverallHealth,
  createInitialHealth,
  getHealthReasons,
  type ServiceStatus,
  type SystemHealth,
} from "@/utils/healthStatus";

const POLL_MS = 45_000;

interface SystemHealthStore extends SystemHealth {
  refresh: () => Promise<void>;
  setRealtime: (status: ServiceStatus) => void;
  setMaps: (status: ServiceStatus) => void;
  setPredictions: (status: ServiceStatus) => void;
}

function buildHealth(
  partial: Pick<
    SystemHealth,
    "api" | "database" | "auth" | "ai" | "predictions" | "maps" | "realtime" | "weather" | "seismic"
  > &
    Partial<Pick<SystemHealth, "aiModel" | "checking" | "lastChecked">>,
): SystemHealth {
  const checking = partial.checking ?? false;
  const overallInput = {
    api: partial.api,
    database: partial.database,
    auth: partial.auth,
    ai: partial.ai,
    predictions: partial.predictions,
    maps: partial.maps,
    realtime: partial.realtime,
    weather: partial.weather,
    seismic: partial.seismic,
    checking,
  };
  const overall = calculateOverallHealth(overallInput);
  const reasons = getHealthReasons({ ...overallInput, overall });
  return {
    api: partial.api,
    database: partial.database,
    auth: partial.auth,
    ai: partial.ai,
    predictions: partial.predictions,
    maps: partial.maps,
    realtime: partial.realtime,
    weather: partial.weather,
    seismic: partial.seismic,
    checking,
    overall,
    reasons,
    lastChecked: partial.lastChecked ?? new Date().toISOString(),
    aiModel: partial.aiModel ?? null,
  };
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let visibilityHandler: (() => void) | null = null;

async function runChecks(): Promise<void> {
  const { setState, getState } = useSystemHealthStore;
  const prev = getState();

  const [apiRes, cmdRes] = await Promise.all([getApiHealth(), getCommandHealth()]);

  const api: ServiceStatus = apiRes.ok ? "ONLINE" : "OFFLINE";
  const database: ServiceStatus = api === "ONLINE" ? "ONLINE" : "OFFLINE";
  // Public demo mode (2026-09): sign-in removed — auth is always available
  // when the backend is reachable.
  const auth: ServiceStatus = api === "OFFLINE" ? "UNKNOWN" : "ONLINE";

  let ai: ServiceStatus;
  let aiModel: string | null = prev.aiModel ?? null;
  if (api === "OFFLINE") {
    ai = "UNKNOWN";
  } else if (!cmdRes.ok) {
    ai = "OFFLINE";
  } else if (cmdRes.data.ai_available) {
    ai = "ONLINE";
    aiModel = cmdRes.data.model;
  } else {
    ai = "DEGRADED";
    aiModel = cmdRes.data.model ?? null;
  }

  const predictions: ServiceStatus =
    api === "ONLINE"
      ? prev.predictions === "DEGRADED" || prev.predictions === "OFFLINE"
        ? prev.predictions
        : "ONLINE"
      : "UNKNOWN";

  // Sticky maps status from CesiumGlobe (token presence)
  const maps: ServiceStatus =
    prev.maps === "DEGRADED" || prev.maps === "ONLINE"
      ? prev.maps
      : prev.maps === "UNKNOWN"
        ? "ONLINE"
        : prev.maps;

  const realtime: ServiceStatus =
    prev.realtime === "UNKNOWN" ? "UNKNOWN" : prev.realtime;

  // Optional external providers (§31): DEGRADED/OFFLINE both surface as
  // DEGRADED — an optional provider never reports OFFLINE to the operator.
  const providers = apiRes.ok ? (apiRes.data.providers ?? {}) : {};
  const optionalProvider = (name: string): ServiceStatus => {
    if (api === "OFFLINE") return "UNKNOWN";
    const status = providers[name]?.status;
    if (status === "ONLINE") return "ONLINE";
    if (status === "DEGRADED" || status === "OFFLINE") return "DEGRADED";
    return "UNKNOWN";
  };
  // Canonical group: ONLINE when the primary OR fallback weather source is
  // serving (open-meteo + met-norway), DEGRADED when either is degraded.
  const weather = optionalProvider("weather");
  const seismic = optionalProvider("usgs");

  setState(
    buildHealth({
      api,
      database,
      auth,
      ai,
      aiModel,
      predictions,
      maps,
      realtime,
      weather,
      seismic,
      checking: false,
    }),
  );
}

export const useSystemHealthStore = create<SystemHealthStore>((set, get) => ({
  ...createInitialHealth(),
  aiModel: null,

  refresh: async () => {
    await runChecks();
  },

  setRealtime: (status) => {
    const prev = get();
    if (prev.realtime === status && !prev.checking) return;
    set(
      buildHealth({
        api: prev.api,
        database: prev.database,
        auth: prev.auth,
        ai: prev.ai,
        aiModel: prev.aiModel,
        predictions: prev.predictions,
        maps: prev.maps,
        realtime: status,
        weather: prev.weather,
        seismic: prev.seismic,
        checking: prev.checking,
      }),
    );
  },

  setMaps: (status) => {
    const prev = get();
    set(
      buildHealth({
        api: prev.api,
        database: prev.database,
        auth: prev.auth,
        ai: prev.ai,
        aiModel: prev.aiModel,
        predictions: prev.predictions,
        maps: status,
        realtime: prev.realtime,
        weather: prev.weather,
        seismic: prev.seismic,
        checking: prev.checking,
      }),
    );
  },

  setPredictions: (status) => {
    const prev = get();
    set(
      buildHealth({
        api: prev.api,
        database: prev.database,
        auth: prev.auth,
        ai: prev.ai,
        aiModel: prev.aiModel,
        predictions: status,
        maps: prev.maps,
        realtime: prev.realtime,
        weather: prev.weather,
        seismic: prev.seismic,
        checking: prev.checking,
      }),
    );
  },
}));

/** Start shared polling once (idempotent). Pauses when tab is hidden. */
export function startSystemHealthPolling(): void {
  if (pollTimer !== null) return;

  void useSystemHealthStore.getState().refresh();

  pollTimer = setInterval(() => {
    if (typeof document !== "undefined" && document.hidden) return;
    void useSystemHealthStore.getState().refresh();
  }, POLL_MS);

  visibilityHandler = () => {
    if (typeof document !== "undefined" && !document.hidden) {
      void useSystemHealthStore.getState().refresh();
    }
  };
  document.addEventListener("visibilitychange", visibilityHandler);
}
