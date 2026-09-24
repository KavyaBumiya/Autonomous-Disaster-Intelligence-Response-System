import React, { useState, useCallback } from "react";
import { toast } from "sonner";
import { routesApi, incidentsApi, apiErrorMessage, type RoutesResult } from "@/services/api";

interface RouteIntelligenceProps {
  zoneId: string;
  incidentId?: string;
}

export const RouteIntelligence: React.FC<RouteIntelligenceProps> = ({
  zoneId,
}) => {
  const [blockedRoads, setBlockedRoads] = useState("");
  const [routes, setRoutes] = useState<RoutesResult | null>(null);
  const [loading, setLoading] = useState(false);

  const computeRoutes = useCallback(async () => {
    if (!blockedRoads.trim()) {
      toast.warning("Please enter blocked road(s)");
      return;
    }
    setLoading(true);
    try {
      let disasterType = "flood";
      try {
        const incRes = await incidentsApi.list({
          zone_id: zoneId,
          active_only: true,
          limit: 1,
        });
        disasterType = incRes.data.incidents?.[0]?.disaster_type || "flood";
      } catch {
        // fall back to flood if incident lookup fails
      }

      const res = await routesApi.compute({
        zone_id: zoneId,
        blocked_roads: blockedRoads,
        disaster_type: disasterType,
      });
      setRoutes(res.data);
      toast.success("Routes computed successfully");
    } catch (err) {
      toast.error(apiErrorMessage(err) || "Route computation failed");
    } finally {
      setLoading(false);
    }
  }, [blockedRoads, zoneId]);

  return (
    <div className="card p-6 max-w-md mx-auto">
      <h2 className="text-2xl font-bold mb-4">Route Intelligence</h2>

      {/* Blocked Roads Input */}
      <div className="mb-4 p-4 bg-gray-800/50 rounded-lg">
        <label className="block text-sm text-gray-300 mb-2">
          Blocked Road(s) — enter road name(s) and reason (comma-separated):
        </label>
        <input
          value={blockedRoads}
          onChange={(e) => setBlockedRoads(e.target.value)}
          placeholder="e.g. Main Highway - landslide, Secondary Road - flooding"
          className="w-full bg-gray-700 rounded py-2 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Routes Display */}
      {routes && (
        <div className="p-4 bg-gray-800/50 rounded-lg mb-4">
          <h3 className="font-medium text-white mb-3">Route Options</h3>

          {/* Primary Route */}
          {routes.primary_route && (
            <div className="mb-3 p-3 bg-blue-800/30 rounded-lg">
              <p className="font-medium text-blue-300">Primary Route</p>
              <p className="text-sm text-gray-300">
                Distance: {routes.primary_route.distance_km} km •
                Estimated time: {routes.primary_route.estimated_minutes} min
              </p>
              <p className="text-xs text-gray-400">
                Note: {routes.primary_route.note || "May be blocked"}
              </p>
            </div>
          )}

          {/* Alternate Routes */}
          {routes.alternate_routes && routes.alternate_routes.length > 0 && (
            <div>
              <p className="font-medium text-white">Alternate Routes:</p>
              {routes.alternate_routes.map((alt, i) => (
                <div key={i} className="mb-2 p-3 bg-gray-700/50 rounded-lg">
                  <p className="font-semibold text-yellow-400">
                    Alternate {i + 1}: {alt.estimated_minutes} min
                  </p>
                  <p className="text-xs text-gray-300">{alt.detour_reason}</p>
                  <p className="text-xs text-gray-400">
                    Distance: {alt.distance_km} km
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* No routes if blocked but no alternates */}
          {(!routes.alternate_routes || routes.alternate_routes.length === 0) &&
            blockedRoads && (
              <p className="text-sm text-yellow-400">
                No alternate routes computed yet.
              </p>
            )}
        </div>
      )}

      {/* Compute button */}
      {loading ? (
        <p className="text-yellow-300">Computing routes...</p>
      ) : (
        <button
          onClick={computeRoutes}
          disabled={!blockedRoads.trim()}
          className="w-full bg-orange-600 text-white font-medium rounded-lg py-2 disabled:opacity-50"
        >
          Compute Alternate Routes
        </button>
      )}
    </div>
  );
};
