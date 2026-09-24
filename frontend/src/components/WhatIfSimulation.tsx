import React, { useState, useCallback } from "react";
import { toast } from "sonner";
import { predictionsApi, apiErrorMessage } from "@/services/api";
import { Button } from "@/components/ui";

interface WhatIfSimulationProps {
  zoneId: string;
  incidentId?: string;
  disasterType: string;
}

interface SimulationResult {
  disaster_type: string;
  new_priority?: number;
  description?: string;
  base_prediction?: { priority_base?: number | string };
  adjusted_prediction?: {
    affected_cells?: unknown[];
    max_intensity?: number;
  };
}

export const WhatIfSimulation: React.FC<WhatIfSimulationProps> = ({
  zoneId,
  disasterType,
}) => {
  const [scenario, setScenario] = useState<"flood" | "fire">("flood");
  const [rainfall, setRainfall] = useState(50);
  const [windSpeed, setWindSpeed] = useState(20);
  const [resourceDelta, setResourceDelta] = useState(0);
  const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const runSimulation = useCallback(async () => {
    setLoading(true);
    try {
      const res = await predictionsApi.whatIf({
        zone_id: zoneId,
        disaster_type: scenario === "fire" ? "fire" : disasterType,
        rainfall_mm_hr: rainfall,
        wind_speed_kmh: windSpeed,
        resource_delta: resourceDelta,
      });
      setSimulationResult(res.data);
      toast.success("What-if simulation complete");
    } catch (err) {
      toast.error(apiErrorMessage(err) || "Simulation failed");
    } finally {
      setLoading(false);
    }
  }, [zoneId, rainfall, windSpeed, resourceDelta, disasterType, scenario]);

  return (
    <div>
      <div className="mb-4 flex gap-1 rounded-lg border border-[var(--line)] bg-white/[.03] p-1" role="tablist">
        <button
          role="tab"
          aria-selected={scenario === "flood"}
          onClick={() => setScenario("flood")}
          className={`ops-nav-link flex-1 justify-center ${scenario === "flood" ? "active" : ""}`}
        >
          Flood scenario
        </button>
        <button
          role="tab"
          aria-selected={scenario === "fire"}
          onClick={() => setScenario("fire")}
          className={`ops-nav-link flex-1 justify-center ${scenario === "fire" ? "active" : ""}`}
        >
          Fire scenario
        </button>
      </div>

      <div className="ops-panel-flat mb-4 p-4">
        <div className="ops-kicker mb-3">
          {scenario === "flood" ? "Flood parameters" : "Fire parameters"}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {scenario === "flood" ? (
            <div>
              <label className="ops-stat-label" htmlFor="rainfall">
                Rainfall (mm/hr)
              </label>
              <input
                id="rainfall"
                type="range"
                min="0"
                max="200"
                step="5"
                value={rainfall}
                onChange={(e) => setRainfall(parseFloat(e.target.value))}
                className="mt-2 w-full accent-[#38d9c4]"
              />
              <div className="ops-mono mt-1 text-xs text-slate-400">{rainfall.toFixed(0)} mm/hr</div>
            </div>
          ) : (
            <>
              <div>
                <label className="ops-stat-label" htmlFor="wind">
                  Wind speed (km/h)
                </label>
                <input
                  id="wind"
                  type="range"
                  min="0"
                  max="200"
                  step="5"
                  value={windSpeed}
                  onChange={(e) => setWindSpeed(parseFloat(e.target.value))}
                  className="mt-2 w-full accent-[#ff6b6b]"
                />
                <div className="ops-mono mt-1 text-xs text-slate-400">{windSpeed.toFixed(0)} km/h</div>
              </div>
              <div>
                <label className="ops-stat-label" htmlFor="resdelta">
                  Resource delta
                </label>
                <select
                  id="resdelta"
                  value={resourceDelta}
                  onChange={(e) => setResourceDelta(parseInt(e.target.value, 10))}
                  className="ops-select mt-2"
                >
                  <option value="-3">-3 resources (higher priority)</option>
                  <option value="-1">-1 resource</option>
                  <option value="0">No change</option>
                  <option value="1">+1 resource</option>
                  <option value="3">+3 resources (lower priority)</option>
                </select>
              </div>
            </>
          )}
        </div>
        <Button
          variant="primary"
          block
          className="mt-4"
          onClick={runSimulation}
          disabled={loading || !zoneId}
        >
          {loading ? "Simulating…" : scenario === "flood" ? "Run flood simulation" : "Run fire simulation"}
        </Button>
      </div>

      {simulationResult && (
        <div className="ops-panel-flat p-4">
          <div className="ops-kicker mb-3">Results — {simulationResult.disaster_type?.toUpperCase()}</div>
          <div className="ops-kpi-grid mb-3" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <div className="ops-stat" style={{ minHeight: 88 }}>
              <div className="ops-stat-label">Base priority</div>
              <div className="ops-stat-value" style={{ fontSize: 22 }}>
                {simulationResult.base_prediction?.priority_base || "N/A"}
              </div>
            </div>
            <div className="ops-stat" style={{ minHeight: 88 }}>
              <div className="ops-stat-label">Adjusted priority</div>
              <div className="ops-stat-value text-[#38d9c4]" style={{ fontSize: 22 }}>
                {simulationResult.new_priority ?? "—"}
              </div>
            </div>
          </div>
          <p className="text-xs leading-5 text-slate-400">{simulationResult.description}</p>
          <div className="ops-mono mt-3 flex flex-wrap gap-4 text-xs text-slate-300">
            <span>
              Affected cells:{" "}
              <strong>{simulationResult.adjusted_prediction?.affected_cells?.length ?? 0}</strong>
            </span>
            <span>
              Max intensity:{" "}
              <strong>{simulationResult.adjusted_prediction?.max_intensity ?? 0}</strong>
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
