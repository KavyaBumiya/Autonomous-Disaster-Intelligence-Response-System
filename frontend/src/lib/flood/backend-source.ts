import type { FloodReading } from "./types";
import { apiUrl } from "../config";

interface FloodDataEnvelope {
  status: "ok" | "no_data";
  reading: FloodReading | null;
  detail?: string;
  age_seconds?: number | null;
}

export class BackendDataSource {
  private handler: ((reading: FloodReading | null) => void) | null = null;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private abortController: AbortController | null = null;

  subscribe(handler: (reading: FloodReading | null) => void): () => void {
    this.handler = handler;
    this.abortController = new AbortController();

    const poll = async () => {
      try {
        const response = await fetch(apiUrl("/api/flood/data"), {
          signal: this.abortController?.signal,
        });
        if (!response.ok) {
          // A failed read is not the same as "no sensor data": report it so the
          // page can say the source is unavailable rather than looking idle.
          this.handler?.(null);
          return;
        }
        const data = (await response.json()) as FloodDataEnvelope;
        this.handler?.(data.status === "ok" ? data.reading : null);
      } catch {
        // AbortError on unmount is expected; anything else means the source is
        // unreachable, which the page renders as an explicit unavailable state.
        if (this.abortController && !this.abortController.signal.aborted) {
          this.handler?.(null);
        }
      }
    };

    void poll();
    // Clear any interval a previous subscribe left running: subscribe() can be
    // called again on a mode toggle, and each leaked timer keeps hitting the API
    // for a page that is no longer mounted.
    if (this.intervalId) clearInterval(this.intervalId);
    this.intervalId = setInterval(poll, 5000);

    return () => {
      if (this.intervalId) clearInterval(this.intervalId);
      this.intervalId = null;
      this.abortController?.abort();
      this.abortController = null;
      this.handler = null;
    };
  }

  disconnect(): void {
    if (this.intervalId) clearInterval(this.intervalId);
    this.intervalId = null;
    this.abortController?.abort();
    this.abortController = null;
    this.handler = null;
  }
}
