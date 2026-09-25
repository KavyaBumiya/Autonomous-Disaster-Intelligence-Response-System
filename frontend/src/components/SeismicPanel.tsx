/**
 * AEGIS-AI — SeismicPanel (Phase 15)
 * Recent earthquakes from the local USGS poll (/api/earthquakes/recent).
 * Empty/error states are honest (§31/§32) — no invented events.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { earthquakesApi } from "@/services/api";

interface SeismicPanelProps {
  /** Look-back window in minutes (default 24 h). */
  minutes?: number;
  limit?: number;
}

const magTone = (mag: number): string =>
  mag >= 6 ? "text-[#ff6b6b]" : mag >= 4.5 ? "text-[#f3b562]" : "text-[#38d9c4]";

export const SeismicPanel: React.FC<SeismicPanelProps> = ({
  minutes = 1440,
  limit = 5,
}) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["earthquakes", "recent", minutes, limit],
    queryFn: () => earthquakesApi.recent({ minutes, limit }).then((r) => r.data),
    staleTime: 60_000,
    refetchInterval: 180_000,
    retry: 1,
  });

  const events = data?.earthquakes ?? [];

  return (
    <div className="ops-panel">
      <div className="ops-panel-header">
        <div>
          <div className="ops-kicker">Seismic feed</div>
          <div className="ops-title">Recent earthquakes</div>
        </div>
        <span className="ops-mono text-xs text-slate-400">USGS</span>
      </div>

      <div className="ops-panel-body">
        {isLoading && (
          <p className="ops-mono animate-pulse text-xs text-slate-500">
            Loading seismic events…
          </p>
        )}

        {isError && (
          <div className="rounded-lg border border-[#f3b562]/30 bg-[#f3b562]/10 px-3 py-2 text-xs text-[#f3b562]">
            Seismic feed unavailable — no events shown rather than fabricated
            ones (§31).
          </div>
        )}

        {!isLoading && !isError && events.length === 0 && (
          <p className="text-xs text-slate-500">
            No seismic events (M≥3) recorded in the last{" "}
            {Math.round(minutes / 60)} h — USGS window is empty.
          </p>
        )}

        {events.length > 0 && (
          <div className="space-y-2">
            {events.slice(0, limit).map((eq) => {
              const id = eq.usgs_id ?? eq.id;
              return (
                <div
                  key={id}
                  className="rounded-lg border border-white/10 bg-white/[.02] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`ops-mono text-sm font-black ${magTone(eq.magnitude)}`}>
                      M {eq.magnitude.toFixed(1)}
                    </span>
                    <span className="text-[10px] text-slate-500">
                      {eq.event_time ? new Date(eq.event_time).toLocaleString() : "—"}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-slate-300">
                    {eq.place_description ?? eq.place ?? "Unknown region"}
                  </div>
                  <div className="ops-mono mt-0.5 text-[10px] text-slate-500">
                    depth {eq.depth_km != null ? `${eq.depth_km.toFixed(0)} km` : "?"} ·{" "}
                    {eq.lat.toFixed(2)}, {eq.lng.toFixed(2)} · risk{" "}
                    {eq.risk_score.toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <p className="mt-2 text-[10px] text-slate-600">
          Source: USGS (local poll, 2-minute cadence) · never fabricated
        </p>
      </div>
    </div>
  );
};
