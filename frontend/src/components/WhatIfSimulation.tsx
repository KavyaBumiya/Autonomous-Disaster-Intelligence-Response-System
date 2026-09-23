import React, { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";

interface WhatIfSimulationProps {
  zoneId: string;
  incidentId: string;
  disasterType: string;
}

export const WhatIfSimulation: React.FC<WhatIfSimulationProps> = ({
  zoneId,
  incidentId,
  disasterType,
}) => {
  const [showFloodTab, setShowFloodTab] = useState(true);
  const [showFireTab, setShowFireTab] = useState(false);
  const [rainfall, setRainfall] = useState(50.0);
  const [windSpeed, setWindSpeed] = useState(20.0);
  const [resourceDelta, setResourceDelta] = useState(0);
  const [simulationResult, setSimulationResult] = useState<null | any>(null);
  const [loading, setLoading] = useState(false);

  const { data: basePrediction } = useQuery({
    queryKey: ["prediction", zoneId, disasterType],
    queryFn: async () => {
      const res = await axios.post(`/api/predictions/${disasterType.toLowerCase()}`, {
        zone_id: zoneId,
        hours: 12,
      });
      return res.data;
    },
    enabled: false,
  });

  const runSimulation = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.post("/api/predictions/what-if", {
        zone_id: zoneId,
        disaster_type: disasterType,
        rainfall_mm_hr: rainfall,
        wind_speed_kmh: windSpeed,
        resource_delta: resourceDelta,
      });
      setSimulationResult(res.data);
      toast.success("What-if simulation complete");
    } catch (err: any) {
      toast.error(err.response?.detail || "Simulation failed");
    } finally {
      setLoading(false);
    }
  }, [rainfall, windSpeed, resourceDelta, disasterType]);

  return (
    <div className="card p-6 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">What-If Simulation</h2>

      <div className="grid grid-cols-2 gap-2 mb-4">
        <button
          onClick={() => { setShowFloodTab(true); setShowFireTab(false); }}
          className={showFloodTab ? "bg-blue-600 text-white rounded-lg py-2 px-4 text-sm font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-2 px-4 text-sm font-medium"}
        >
          Flood Scenario
        </button>
        <button
          onClick={() => { setShowFireTab(true); setShowFloodTab(false); }}
          className={showFireTab ? "bg-blue-600 text-white rounded-lg py-2 px-2 text-sm font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-2 px-2 text-sm font-medium"}
        >
          Fire Scenario
        </button>
      </div>

      {/* Flood Tab */}
      {showFloodTab && (
        <div className="p-4 bg-gray-800/50 rounded-lg mb-4">
          <h3 className="font-medium text-white mb-3">Flood Parameters</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm text-gray-300">Rainfall (mm/hr)</label>
              <input
                type="range"
                min="0"
                max="200"
                step="5"
                value={rainfall}
                onChange={(e) => setRainfall(parseFloat(e.target.value))}
                className="w-full bg-gray-700 rounded h-2 accent-blue-600"
              />
              <div className="text-xs text-gray-400 mt-1">
                {rainfall.toFixed(1)} mm/hr
              </div>
            </div>
          </div>
          <button
            onClick={runSimulation}
            disabled={loading}
            className="mt-3 w-full bg-blue-600 text-white font-medium rounded-lg py-2 disabled:opacity-50"
          >
            {loading ? "Simulating..." : "Run Flood Simulation"}
          </button>
        </div>
      )}

      {/* Fire Tab */}
      {showFireTab && (
        <div className="p-4 bg-gray-800/50 rounded-lg mb-4">
          <h3 className="font-medium text-white mb-3">Fire Parameters</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm text-gray-300">Wind Speed (km/h)</label>
              <input
                type="range"
                min="0"
                max="200"
                step="5"
                value={windSpeed}
                onChange={(e) => setWindSpeed(parseFloat(e.target.value))}
                className="w-full bg-gray-700 rounded h-2 accent-red-600"
              />
              <div className="text-xs text-gray-400 mt-1">
                {windSpeed.toFixed(1)} km/h
              </div>
            </div>
            <div>
              <label className="text-sm text-gray-300">Resource Delta</label>
              <select
                value={resourceDelta}
                onChange={(e) => setResourceDelta(parseInt(e.target.value))}
                className="w-full bg-gray-700 rounded py-2 text-sm"
              >
                <option value="-3">-3 Resources (higher priority)</option>
                <option value="-1">-1 Resource</option>
                <option value="0">No change</option>
                <option value="1">+1 Resource</option>
                <option value="3">+3 Resources (lower priority)</option>
              </select>
            </div>
          </div>
          <button
            onClick={runSimulation}
            disabled={loading}
            className="mt-3 w-full bg-red-600 text-white font-medium rounded-lg py-2 disabled:opacity-50"
          >
            {loading ? "Simulating..." : "Run Fire Simulation"}
          </button>
        </div>
      )}

      {/* Results */}
      {simulationResult && (
        <div className="mt-6 p-4 bg-gray-800/50 rounded-lg">
          <h3 className="font-medium text-white mb-3">
            Results — {simulationResult.disaster_type.toUpperCase()}
          </h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-gray-400">Base Priority:</span>
              <span className="font-bold text-yellow-400">
                {simulationResult.base_prediction?.priority_base || "N/A"}
              </span>
            </div>
            <div>
              <span className="text-gray-400">Adjusted Priority:</span>
              <span className="font-bold text-green-400">
                {simulationResult.new_priority}
              </span>
            </div>
          </div>

          <p className="text-xs text-gray-300 mt-2">
            {simulationResult.description}
          </p>

          {/* Affected cells / burned area summary */}
          {simulationResult.adjusted_prediction && simulationResult.adjusted_prediction.affected_cells
            ? (
              <div>
                <span className="text-gray-400">Affected cells:</span>
                <span className="font-bold text-white">
                  {simulationResult.adjusted_prediction.affected_cells.length}
                </span>
              </div>
            )
            : (
              <div>
                <span className="text-gray-400">Affected cells:</span>
                <span className="font-bold text-white">0</span>
              </div>
            )}
          {simulationResult.adjusted_prediction && simulationResult.adjusted_prediction.max_intensity
            ? (
              <div>
                <span className="text-gray-400">Max intensity:</span>
                <span className="font-bold text-yellow-400">
                  {simulationResult.adjusted_prediction.max_intensity}
                </span>
              </div>
            )
            : (
              <div>
                <span className="text-gray-400">Max intensity:</span>
                <span className="font-bold text-yellow-400">0</span>
              </div>
            )}
        </div>
      )}
    </div>
  );
};