/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute origin of the AegisAI backend, e.g. https://api.aegis.example. Leave empty to use the dev proxy / same origin. */
  readonly VITE_API_BASE_URL?: string;
  /** Absolute origin for the Socket.IO feed. Defaults to VITE_API_BASE_URL. */
  readonly VITE_SOCKET_URL?: string;
  /** Poll cadence for operational panels, in milliseconds. Default 15000. */
  readonly VITE_POLL_INTERVAL_MS?: string;
  /** Timeout for standard REST calls, in milliseconds. Default 20000. */
  readonly VITE_REQUEST_TIMEOUT_MS?: string;
  /** Longer timeout for AI-backed calls (POST /api/command/query). Default 90000. */
  readonly VITE_COMMAND_TIMEOUT_MS?: string;
  /** Pin the primary zone by id. Leave empty to resolve the highest-priority zone from GET /api/zones. */
  readonly VITE_ZONE_ID?: string;
  /** Mapbox access token for the 2D live map. */
  readonly VITE_MAPBOX_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
