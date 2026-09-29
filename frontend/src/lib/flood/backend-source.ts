import type { FloodReading } from "./types";
import { apiUrl } from "../config";

export class BackendDataSource {
  private handler: ((reading: FloodReading) => void) | null = null;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private abortController: AbortController | null = null;

  subscribe(handler: (reading: FloodReading) => void): () => void {
    this.handler = handler;
    this.abortController = new AbortController();

    const poll = async () => {
      try {
        const response = await fetch(apiUrl("/api/flood/data"), {
          signal: this.abortController?.signal,
        });
        if (response.ok) {
          const data = (await response.json()) as FloodReading;
          this.handler?.(data);
        }
      } catch {
        // Silently retry on next poll
      }
    };

    void poll();
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
  }
}
