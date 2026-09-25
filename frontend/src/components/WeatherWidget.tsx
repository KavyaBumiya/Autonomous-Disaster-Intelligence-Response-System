/**
 * AEGIS-AI — WeatherWidget (Phase 15)
 * Compact ops-panel showing live Open-Meteo conditions + short forecast
 * for a zone/point. Source-labelled; provider failures render DEGRADED
 * (never fabricated values — PRD §31).
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { weatherApi } from "@/services/api";

interface WeatherWidgetProps {
  lat: number;
  lng: number;
  /** Shown in the panel header (e.g. zone name). */
  label?: string;
}

const RISK_TONE = (risk: number): string =>
  risk >= 0.5 ? "text-[#ff6b6b]" : risk >= 0.2 ? "text-[#f3b562]" : "text-[#38d9c4]";

const RISK_LABEL = (risk: number): string =>
  risk >= 0.5 ? "HIGH" : risk >= 0.2 ? "WATCH" : "CALM";

export const WeatherWidget: React.FC<WeatherWidgetProps> = ({ lat, lng, label }) => {
  const current = useQuery({
    queryKey: ["weather", "current", lat.toFixed(3), lng.toFixed(3)],
    queryFn: () => weatherApi.current(lat, lng).then((r) => r.data),
    staleTime: 120_000,
    refetchInterval: 300_000,
    retry: 1,
  });

  const forecast = useQuery({
    queryKey: ["weather", "forecast", lat.toFixed(3), lng.toFixed(3), 6],
    queryFn: () => weatherApi.forecast(lat, lng, 6).then((r) => r.data),
    staleTime: 300_000,
    refetchInterval: 600_000,
    retry: 1,
  });

  const data = current.data;

  return (
    <div className="ops-panel">
      <div className="ops-panel-header">
        <div>
          <div className="ops-kicker">Weather intelligence</div>
          <div className="ops-title">{label || "Live conditions"}</div>
        </div>
        <span className="ops-mono text-xs text-slate-400">OPEN-METEO</span>
      </div>

      <div className="ops-panel-body">
        {current.isLoading && (
          <p className="ops-mono animate-pulse text-xs text-slate-500">
            Loading live weather…
          </p>
        )}

        {current.isError && (
          <div className="rounded-lg border border-[#f3b562]/30 bg-[#f3b562]/10 px-3 py-2 text-xs text-[#f3b562]">
            Weather provider unavailable — showing no data rather than
            fabricating values (§31). Deterministic services remain online.
          </div>
        )}

        {data && (
          <>
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <div className="ops-mono text-3xl font-black text-white">
                  {data.temperature_c != null ? `${Math.round(data.temperature_c)}°C` : "—"}
                </div>
                <div className="mt-0.5 text-xs text-slate-400">
                  {data.weather_description || data.weather_main || "—"}
                </div>
              </div>
              <div className="text-right">
                <div className={`ops-mono text-lg font-bold ${RISK_TONE(data.risk_score)}`}>
                  {RISK_LABEL(data.risk_score)}
                </div>
                <div className="ops-mono text-[10px] text-slate-500">
                  risk {data.risk_score.toFixed(2)}
                </div>
              </div>
            </div>

            <div className="mb-3 grid grid-cols-3 gap-2 text-center">
              <Stat label="Rain" value={`${data.rainfall_mm_hr.toFixed(1)} mm/h`} />
              <Stat label="Wind" value={`${Math.round(data.wind_speed_kmh)} km/h`} />
              <Stat label="Humidity" value={data.humidity_pct != null ? `${Math.round(data.humidity_pct)}%` : "—"} />
            </div>

            {forecast.data && forecast.data.hours.length > 0 && (
              <div>
                <div className="ops-kicker mb-2">Next hours (precipitation)</div>
                <div className="flex gap-1.5 overflow-x-auto pb-1">
                  {forecast.data.hours.slice(0, 6).map((h) => (
                    <div
                      key={h.time}
                      className="min-w-[52px] rounded-lg border border-white/10 bg-white/[.03] px-1.5 py-1.5 text-center"
                    >
                      <div className="ops-mono text-[10px] text-slate-500">
                        {h.time.slice(11, 16) || "--:--"}
                      </div>
                      <div className="ops-mono text-xs font-bold text-[#38d9c4]">
                        {h.precipitation_mm.toFixed(1)}
                      </div>
                      <div className="text-[9px] text-slate-600">mm</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="mt-2 text-[10px] text-slate-600">
              Source: {data.provider} ·{" "}
              {data.from_cache ? "cached reading (labelled)" : "live fetch"} · never
              fabricated
            </p>
          </>
        )}
      </div>
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-white/10 bg-white/[.03] px-2 py-1.5">
    <div className="ops-mono text-[9px] uppercase tracking-wider text-slate-500">
      {label}
    </div>
    <div className="ops-mono text-xs font-bold text-slate-200">{value}</div>
  </div>
);
