/**
 * Runtime configuration for talking to the AegisAI backend.
 *
 * The frontend and the backend are deployed independently, so the API origin
 * is resolved entirely from build-time environment variables. Nothing here is
 * hard-coded to a host: an empty `VITE_API_BASE_URL` means "same origin",
 * which is what the Vite dev proxy and same-host reverse-proxy deployments use.
 */

/** Strip whitespace and any trailing slashes so path joining stays predictable. */
const normaliseOrigin = (value: string | undefined): string =>
  (value ?? "").trim().replace(/\/+$/, "");

const positiveInt = (value: string | undefined, fallback: number): number => {
  const parsed = Number.parseInt((value ?? "").trim(), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

/** Absolute API origin, or "" when the app should call its own origin. */
export const API_BASE = normaliseOrigin(import.meta.env.VITE_API_BASE_URL);

/** Socket.IO origin. Falls back to the API origin, then to the page origin. */
export const SOCKET_BASE =
  normaliseOrigin(import.meta.env.VITE_SOCKET_URL) || API_BASE;

/** True when the dev proxy (or a reverse proxy) fronts the backend for us. */
export const USING_DEV_PROXY = API_BASE === "";

/** Build a fully-qualified request URL for a backend path such as "/api/health". */
export const apiUrl = (path: string): string => {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${suffix}`;
};

/** Socket.IO connect target. Empty string lets socket.io-client use the page origin. */
export const socketUrl = (): string => SOCKET_BASE;

/** Cadence at which operational panels re-poll. */
export const POLL_INTERVAL_MS = positiveInt(
  import.meta.env.VITE_POLL_INTERVAL_MS,
  15_000,
);

/** Timeout applied to ordinary REST reads. */
export const REQUEST_TIMEOUT_MS = positiveInt(
  import.meta.env.VITE_REQUEST_TIMEOUT_MS,
  20_000,
);

/**
 * Timeout for AI-backed calls. The gateway probes NVIDIA NIM and can run up to
 * five tool rounds, so this needs considerably more headroom than a data read.
 */
export const COMMAND_TIMEOUT_MS = positiveInt(
  import.meta.env.VITE_COMMAND_TIMEOUT_MS,
  90_000,
);

/** Optional operator pin for the primary zone; otherwise resolved from /api/zones. */
export const PINNED_ZONE_ID = (import.meta.env.VITE_ZONE_ID ?? "").trim();

/** Mapbox access token for the 2D live map. */
export const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
