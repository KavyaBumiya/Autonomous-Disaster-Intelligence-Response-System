/**
 * AEGIS-AI — Shared system health store (zustand)
 * One poller for all badge/detail consumers. No per-component health logic.
 */
import { create } from "zustand";
import { getApiHealth, getCommandHealth } from "@/services/health";
import { onAuthChange } from "@/services/api";
import {
  calculateOverallHealth,
  createInitialHealth,
  getHealthReasons,
  type ServiceStatus,
  type SystemHealth,
} from "@/utils/healthStatus";

const POLL_MS = 45_000;
const TOKEN_KEY = "aegis_token";

function readAuthStatus(): ServiceStatus {
  if (typeof window === "undefined") return "UNKNOWN";
  return localStorage.getItem(TOKEN_KEY) ? "ONLINE" : "REQUIRED";
}

interface SystemHealthStore extends SystemHealth {
  refresh: () => Promise<void>;
  setRealtime: (status: ServiceStatus) => void;
  setMaps: (status: ServiceStatus) => void;
  setPredictions: (status: ServiceStatus) => void;
  setAuth: (status: ServiceStatus) => void;
}

function buildHealth(
  partial: Pick<
    SystemHealth,
    "api" | "database" | "auth" | "groq" | "predictions" | "maps" | "realtime"
  > &
    Partial<Pick<SystemHealth, "groqModel" | "checking" | "lastChecked">>,
): SystemHealth {
  const checking = partial.checking ?? false;
  const overallInput = {
    api: partial.api,
    database: partial.database,
    auth: partial.auth,
    groq: partial.groq,
    predictions: partial.predictions,
    maps: partial.maps,
    realtime: partial.realtime,
    checking,
  };
  const overall = calculateOverallHealth(overallInput);
  const reasons = getHealthReasons({ ...overallInput, overall });
  return {
    api: partial.api,
    database: partial.database,
    auth: partial.auth,
    groq: partial.groq,
    predictions: partial.predictions,
    maps: partial.maps,
    realtime: partial.realtime,
    checking,
    overall,
    reasons,
    lastChecked: partial.lastChecked ?? new Date().toISOString(),
    groqModel: partial.groqModel ?? null,
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
  const auth: ServiceStatus = api === "OFFLINE" ? "UNKNOWN" : readAuthStatus();

  let groq: ServiceStatus;
  let groqModel: string | null = prev.groqModel ?? null;
  if (api === "OFFLINE") {
    groq = "UNKNOWN";
  } else if (!cmdRes.ok) {
    groq = "OFFLINE";
  } else if (cmdRes.data.groq_available) {
    groq = "ONLINE";
    groqModel = cmdRes.data.model;
  } else {
    groq = "DEGRADED";
    groqModel = cmdRes.data.model ?? null;
  }

  const predictions: ServiceStatus =
    api === "ONLINE"
      ? prev.predictions === "DEGRADED" || prev.predictions === "OFFLINE"
        ? prev.predictions
        : "ONLINE"
      : "UNKNOWN";

  // Sticky maps status from OperationalMap (token presence)
  const maps: ServiceStatus =
    prev.maps === "DEGRADED" || prev.maps === "ONLINE"
      ? prev.maps
      : prev.maps === "UNKNOWN"
        ? "ONLINE"
        : prev.maps;

  const realtime: ServiceStatus =
    prev.realtime === "UNKNOWN" ? "UNKNOWN" : prev.realtime;

  setState(
    buildHealth({
      api,
      database,
      auth,
      groq,
      groqModel,
      predictions,
      maps,
      realtime,
      checking: false,
    }),
  );
}

export const useSystemHealthStore = create<SystemHealthStore>((set, get) => ({
  ...createInitialHealth(),
  groqModel: null,

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
        groq: prev.groq,
        groqModel: prev.groqModel,
        predictions: prev.predictions,
        maps: prev.maps,
        realtime: status,
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
        groq: prev.groq,
        groqModel: prev.groqModel,
        predictions: prev.predictions,
        maps: status,
        realtime: prev.realtime,
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
        groq: prev.groq,
        groqModel: prev.groqModel,
        predictions: status,
        maps: prev.maps,
        realtime: prev.realtime,
        checking: prev.checking,
      }),
    );
  },

  setAuth: (status) => {
    const prev = get();
    if (prev.auth === status && !prev.checking) return;
    set(
      buildHealth({
        api: prev.api,
        database: prev.database,
        auth: status,
        groq: prev.groq,
        groqModel: prev.groqModel,
        predictions: prev.predictions,
        maps: prev.maps,
        realtime: prev.realtime,
        checking: prev.checking,
      }),
    );
  },
}));

/** Start shared polling once (idempotent). Pauses when tab is hidden. */
export function startSystemHealthPolling(): void {
  if (pollTimer !== null) return;

  onAuthChange((authenticated) => {
    useSystemHealthStore.getState().setAuth(authenticated ? "ONLINE" : "REQUIRED");
    void useSystemHealthStore.getState().refresh();
  });

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
