import type { FloodReading } from "./types";
import { apiUrl } from "../config";

interface LatestReading {
  device_id: string;
  water_level: number;
  flow_velocity: number;
  timestamp: string;
  received_at: string;
  age_seconds: number | null;
  risk_level: string | null;
  risk_score: number | null;
  device_status: string | null;
  battery_pct: number | null;
  signal_strength: number | null;
}

interface HistoryPoint {
  water_level: number;
  flow_velocity: number;
  timestamp: string;
  risk_level: string | null;
  risk_score: number | null;
}

function toReading(r: LatestReading): FloodReading {
  return {
    water_level: r.water_level,
    flow_velocity: r.flow_velocity,
    timestamp: r.timestamp,
    risk_level: r.risk_level,
  };
}

export class BackendDataSource {
  private handler: ((reading: FloodReading | null) => void) | null = null;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private abortController: AbortController | null = null;
  private deviceId: string | null;
  private resolveAbort: AbortController | null = null;

  constructor(deviceId?: string | null) {
    this.deviceId = deviceId ?? null;
  }

  /**
   * Pick a device when the caller did not name one.
   *
   * Hardcoding an id would make Live mode 404 on any deployment that has not
   * enrolled that exact sensor, which reads as "backend broken" rather than
   * "no device yet". Resolving from the registry keeps the page honest: if
   * nothing is enrolled it reports no data instead of silently picking one.
   */
  private async resolveDeviceId(signal: AbortSignal): Promise<string | null> {
    if (this.deviceId) return this.deviceId;

    this.resolveAbort = new AbortController();
    const onAbort = () => this.resolveAbort?.abort();
    signal.addEventListener("abort", onAbort);
    try {
      const res = await fetch(apiUrl("/api/iot/v1/devices"), {
        signal: this.resolveAbort.signal,
      });
      if (!res.ok) return null;
      const list = (await res.json()) as Array<{ device_id: string }>;
      this.deviceId = list[0]?.device_id ?? null;
      return this.deviceId;
    } catch {
      return null;
    } finally {
      this.resolveAbort = null;
      signal.removeEventListener("abort", onAbort);
    }
  }

  subscribe(handler: (reading: FloodReading | null) => void): () => void {
    this.handler = handler;
    this.abortController = new AbortController();

    const poll = async () => {
      try {
        const deviceId = await this.resolveDeviceId(
          this.abortController?.signal ?? new AbortController().signal,
        );
        if (!deviceId) {
          this.handler?.(null);
          return;
        }
        const response = await fetch(
          apiUrl(`/api/iot/v1/devices/${encodeURIComponent(deviceId)}/latest`),
          { signal: this.abortController?.signal },
        );
        if (!response.ok) {
          this.handler?.(null);
          return;
        }
        const data = (await response.json()) as LatestReading;
        this.handler?.(toReading(data));
      } catch {
        if (this.abortController && !this.abortController.signal.aborted) {
          this.handler?.(null);
        }
      }
    };

    void poll();
    if (this.intervalId) clearInterval(this.intervalId);
    this.intervalId = setInterval(poll, 5000);

    return () => {
      if (this.intervalId) clearInterval(this.intervalId);
      this.intervalId = null;
      this.resolveAbort?.abort();
      this.resolveAbort = null;
      this.abortController?.abort();
      this.abortController = null;
      this.handler = null;
    };
  }

  async getHistory(limit = 100): Promise<FloodReading[]> {
    try {
      const deviceId = this.deviceId ?? (await this.resolveDeviceId(new AbortController().signal));
      if (!deviceId) return [];
      const response = await fetch(
        apiUrl(
          `/api/iot/v1/devices/${encodeURIComponent(deviceId)}/history?limit=${limit}`,
        ),
      );
      if (!response.ok) return [];
      const rows = (await response.json()) as HistoryPoint[];
      return rows.map((r) => ({
        water_level: r.water_level,
        flow_velocity: r.flow_velocity,
        timestamp: r.timestamp,
        risk_level: r.risk_level,
      }));
    } catch {
      return [];
    }
  }

  disconnect(): void {
    if (this.intervalId) clearInterval(this.intervalId);
    this.intervalId = null;
    this.resolveAbort?.abort();
    this.resolveAbort = null;
    this.abortController?.abort();
    this.abortController = null;
    this.handler = null;
  }
}
