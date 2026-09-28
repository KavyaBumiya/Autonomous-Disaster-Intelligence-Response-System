/**
 * Socket.IO feed client.
 *
 * The backend mounts a Socket.IO ASGI app at the same origin as the REST API
 * (`socketio.ASGIApp` in `app/main.py`) and publishes incident, report,
 * priority, prediction, resource and route events.
 *
 * This module is intentionally connection-failure tolerant: the operator console
 * must keep working when the socket is unavailable, so the REST poll in
 * `hooks.ts` remains the source of truth and the socket is only used to trigger
 * a refresh. A dropped socket never surfaces an error to the UI — it is reported
 * through `LiveFeedStatus` instead, so the health badge can never claim the
 * stream is healthy while the socket is actually down.
 */
import { io, type Socket } from "socket.io-client";
import { socketUrl } from "./config";

/** Event names emitted by `app/services/websocket.py`. */
export const SOCKET_EVENTS = [
  "new_report",
  "new_incident",
  "trust_score_updated",
  "incident_priority_updated",
  "action_state_changed",
  "evidence_updated",
  "prediction_updated",
  "resource_status_updated",
  "resource_assigned",
  "route_changed",
  "weather.updated",
  "earthquake.detected",
] as const;

export type SocketEvent = (typeof SOCKET_EVENTS)[number];

let socket: Socket | null = null;
let consumerCount = 0;

/**
 * Live-channel state, reported separately from connection errors so the UI can
 * distinguish "still dialling" from "gave up".
 */
export type LiveFeedStatus = "connecting" | "connected" | "disconnected";

/**
 * Starts as "connecting": the console subscribes on mount, so the initial
 * handshake is normally in flight. An actual failure flips this to
 * "disconnected" via the `connect_error` handler below.
 */
let status: LiveFeedStatus = "connecting";
const statusListeners = new Set<(next: LiveFeedStatus) => void>();

function setStatus(next: LiveFeedStatus): void {
  if (status === next) return;
  status = next;
  for (const listener of statusListeners) listener(next);
}

/**
 * Observe live-channel state changes.
 *
 * The listener is invoked immediately with the current status so a caller never
 * renders a stale value, and the returned function unsubscribes it.
 */
export function onLiveFeedStatusChange(
  listener: (next: LiveFeedStatus) => void,
): () => void {
  statusListeners.add(listener);
  listener(status);
  return () => {
    statusListeners.delete(listener);
  };
}

/**
 * Lazily create the shared socket.
 *
 * `autoConnect` is off so a headless or offline environment never throws during
 * module evaluation; connection is attempted on first subscription.
 */
function getSocket(): Socket {
  if (socket) return socket;

  const target = socketUrl();
  socket = io(target || undefined, {
    path: "/socket.io",
    transports: ["websocket", "polling"],
    autoConnect: false,
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 10_000,
    // Bounded: the console runs standalone against the offline fallback, so a
    // missing backend must not produce an unbounded stream of console errors.
    // Polling still drives the UI; a later manual refresh re-arms the socket.
    reconnectionAttempts: 8,
    timeout: 8000,
  });

  // The server accepts an unauthenticated handshake and routes the client into
  // the global feed room. Errors are swallowed by design (see module docstring),
  // but the resulting state is published so the health badge stays honest.
  socket.on("connect", () => setStatus("connected"));
  socket.on("disconnect", () => setStatus("disconnected"));
  socket.on("connect_error", () => setStatus("disconnected"));

  return socket;
}

/**
 * Subscribe to the live feed.
 *
 * @param handler Called with the event name and its payload.
 * @param subscribe List of events to listen for. Defaults to every known event.
 * @returns An unsubscribe function.
 */
export function subscribeLiveFeed(
  handler: (event: SocketEvent, payload: unknown) => void,
  events: readonly SocketEvent[] = SOCKET_EVENTS,
): () => void {
  const client = getSocket();
  consumerCount += 1;

  const bound = events.map((event) => {
    const listener = (payload: unknown) => handler(event, payload);
    client.on(event, listener);
    return { event, listener };
  });

  if (!client.connected) {
    setStatus("connecting");
    client.connect();
  }
  client.emit("subscribe", { room: "global_feed" });

  return () => {
    for (const { event, listener } of bound) client.off(event, listener);
    client.emit("unsubscribe", { room: "global_feed" });
    consumerCount -= 1;
    // Keep the socket alive only while something is listening; React StrictMode
    // mounts effects twice in development, so closing eagerly would thrash.
    if (consumerCount <= 0) {
      // Only the per-subscriber listeners are dropped here. A blanket
      // removeAllListeners() would also strip the connect/disconnect handlers
      // that publish LiveFeedStatus, leaving the badge frozen on its last value.
      client.disconnect();
      setStatus("disconnected");
    }
  };
}
