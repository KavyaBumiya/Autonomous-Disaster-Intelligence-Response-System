/**
 * Data hooks for the operator console.
 *
 * Every hook follows the same contract: it never throws into render, it always
 * exposes the last good value, and it reports staleness so panels can keep their
 * offline fallbacks. Polling is the primary refresh mechanism (robust across
 * proxies and CDNs); the Socket.IO feed simply triggers an early refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { PINNED_ZONE_ID, POLL_INTERVAL_MS } from "./config";
import { hasData } from "./format";
import { pickPrimaryZone } from "./mappers";
import { subscribeLiveFeed, onLiveFeedStatusChange, type LiveFeedStatus, type SocketEvent } from "./socket";
import type {
  ApprovalQueueResponse,
  AvailableResourcesResponse,
  CommandHealthResponse,
  HealthResponse,
  Incident,
  PredictionsResponse,
  Resource,
  Report,
  RoutesResponse,
  Zone,
} from "./types";

export interface AsyncResource<T> {
  data: T | null;
  error: string | null;
  /** True only on the very first load, so panels do not flash on every poll. */
  isInitialLoading: boolean;
  lastUpdatedAt: number | null;
  refresh: () => void;
}

/**
 * Poll an endpoint, keeping the last successful payload.
 *
 * @param fetcher Performs the request. Receives an AbortSignal.
 * @param key Changing this restarts the request and clears stale data.
 * @param options.intervalMs Poll cadence; 0 disables polling.
 * @param options.enabled Skip fetching entirely (e.g. no zone resolved yet).
 */
export function useApiResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  key: string,
  options: { intervalMs?: number; enabled?: boolean } = {},
): AsyncResource<T> {
  const { intervalMs = POLL_INTERVAL_MS, enabled = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isInitialLoading, setInitialLoading] = useState(enabled);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);

  // Keep the latest fetcher without making it a dependency, so callers can
  // pass an inline closure without restarting the poll loop every render.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) {
      setInitialLoading(false);
      return undefined;
    }

    let cancelled = false;
    const controller = new AbortController();

    const run = async () => {
      try {
        const result = await fetcherRef.current(controller.signal);
        if (cancelled) return;
        setData(result);
        setError(null);
        setLastUpdatedAt(Date.now());
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        // Keep the previous payload: a single failed poll must not blank a panel.
        setError(err instanceof ApiError ? err.detail : "Backend unreachable");
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    };

    void run();
    const timer = intervalMs > 0 ? setInterval(run, intervalMs) : undefined;

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [key, enabled, intervalMs, nonce]);

  // A new key means a different resource; do not show the previous one first.
  useEffect(() => {
    setData(null);
    setLastUpdatedAt(null);
    setError(null);
    setInitialLoading(enabled);
  }, [key, enabled]);

  return { data, error, isInitialLoading, lastUpdatedAt, refresh };
}

/**
 * Refresh the provided resources whenever the live feed publishes an event.
 * Polling still runs; this just makes the console feel immediate.
 */
export function useLiveRefresh(resources: Array<{ refresh: () => void }>): void {
  const refreshRef = useRef(resources);
  refreshRef.current = resources;

  useEffect(() => {
    const events: readonly SocketEvent[] = [
      "new_incident",
      "incident_priority_updated",
      "new_report",
      "trust_score_updated",
      "evidence_updated",
      "prediction_updated",
      "resource_status_updated",
      "resource_assigned",
      "route_changed",
      "weather.updated",
      "earthquake.detected",
    ];

    return subscribeLiveFeed(() => {
      for (const resource of refreshRef.current) resource.refresh();
    }, events);
  }, []);
}

// ── Domain hooks ─────────────────────────────────────────────────────────

/**
 * Track the live channel's real connection state.
 *
 * Polling keeps the console populated even while the socket is down, so REST
 * health alone cannot distinguish "stream is fine" from "stream is silently
 * gone". The health badge reads this so it cannot report a healthy stream while
 * the WebSocket is actually down.
 */
export function useLiveFeedStatus(): LiveFeedStatus {
  const [status, setStatusState] = useState<LiveFeedStatus>("connecting");

  useEffect(() => onLiveFeedStatusChange(setStatusState), []);

  return status;
}

export function useHealth() {
  return useApiResource<HealthResponse>((signal) => api.health(signal), "health", {
    intervalMs: 30_000,
  });
}

export function useCommandHealth() {
  return useApiResource<CommandHealthResponse>((signal) => api.commandHealth(signal), "command-health", {
    intervalMs: 60_000,
  });
}

export function useZones() {
  return useApiResource<Zone[]>(
    (signal) => api.zones(signal).then((result) => result.zones),
    "zones",
    { intervalMs: 60_000 },
  );
}

export function useIncidents(zoneId?: string) {
  return useApiResource<Incident[]>(
    (signal) => api.incidents({ activeOnly: true, limit: 50, zoneId }, signal).then((r) => r.incidents),
    `incidents:${zoneId ?? "all"}`,
  );
}

export function useResources(zoneId?: string) {
  return useApiResource<Resource[]>(
    (signal) => api.resources(zoneId ? { zoneId } : {}, signal).then((r) => r.resources),
    `resources:${zoneId ?? "all"}`,
  );
}

export function useReports(zoneId?: string) {
  return useApiResource<Report[]>(
    (signal) => api.reports({ zoneId, limit: 100, minTrust: 0.25 }, signal).then((r) => r.reports),
    `reports:${zoneId ?? "all"}`,
  );
}

export function useTeamResources() {
  return useApiResource<Resource[]>(
    (signal) => api.resources({ resourceType: "team" }, signal).then((r) => r.resources),
    "resources:teams",
  );
}

export function useAvailableResources() {
  return useApiResource<AvailableResourcesResponse>(
    (signal) => api.availableResources(signal),
    "resources:available",
    { intervalMs: 30_000 },
  );
}

export function useApprovalQueue() {
  return useApiResource<ApprovalQueueResponse>(
    (signal) => api.approvalQueue(signal),
    "approval-queue",
    { intervalMs: 45_000 },
  );
}

export function usePredictions(zoneId: string | null) {
  return useApiResource<PredictionsResponse>(
    (signal) => api.predictions(zoneId as string, signal),
    `predictions:${zoneId ?? "none"}`,
    { intervalMs: 60_000, enabled: Boolean(zoneId) },
  );
}

export function useRoutes(zoneId: string | null) {
  return useApiResource<RoutesResponse>(
    (signal) => api.computeRoutes({ zone_id: zoneId as string }, signal),
    `routes:${zoneId ?? "none"}`,
    { intervalMs: 60_000, enabled: Boolean(zoneId) },
  );
}

/**
 * The zone the console focuses on: the operator's pinned zone when configured,
 * otherwise the highest-priority zone the backend knows about.
 */
export function usePrimaryZoneId(zones: Zone[] | null): string | null {
  return useMemo(() => {
    if (PINNED_ZONE_ID) return PINNED_ZONE_ID;
    if (!hasData(zones)) return null;
    return pickPrimaryZone(zones)?.zone_id ?? null;
  }, [zones]);
}

/** Zone-id to display-name lookup, used by the team table. */
export function useZoneNames(zones: Zone[] | null): Map<string, string> {
  return useMemo(
    () => new Map((zones ?? []).map((zone) => [zone.zone_id, zone.name])),
    [zones],
  );
}
