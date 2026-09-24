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
    <div>
      <div className="ops-kicker mb-3">Route intelligence</div>
      <div className="ops-panel-flat mb-4 p-4">
        <label className="ops-stat-label mb-2 block" htmlFor="blocked-roads">
          Blocked road(s) — road name and reason, comma-separated
        </label>
        <input
          id="blocked-roads"
          value={blockedRoads}
          onChange={(e) => setBlockedRoads(e.target.value)}
          placeholder="e.g. Main Highway - landslide, Secondary Road - flooding"
          className="ops-input"
        />
      </div>

      {routes && (
        <div className="ops-panel-flat mb-4 p-4">
          <div className="ops-kicker mb-3">Route options</div>

          {routes.primary_route && (
            <div className="ops-stat mb-3" style={{ minHeight: "auto" }}>
              <div className="ops-badge ops-badge-cyan mb-2">Primary</div>
              <p className="ops-mono text-sm text-slate-200">
                {routes.primary_route.distance_km} km · {routes.primary_route.estimated_minutes} min
              </p>
              <p className="mt-1 text-xs text-slate-400">
                {routes.primary_route.note || "May be blocked"}
              </p>
            </div>
          )}

          {routes.alternate_routes && routes.alternate_routes.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-semibold text-white">Alternates</div>
              {routes.alternate_routes.map((alt, i) => (
                <div key={i} className="ops-list-item">
                  <span className="ops-badge ops-badge-amber">Alt {i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="ops-mono block text-sm text-slate-200">
                      {alt.estimated_minutes} min · {alt.distance_km} km
                    </span>
                    <span className="block text-xs text-slate-400">{alt.detour_reason}</span>
                  </span>
                </div>
              ))}
            </div>
          )}

          {(!routes.alternate_routes || routes.alternate_routes.length === 0) && blockedRoads && (
            <p className="text-sm text-[#f3b562]">No alternate routes computed yet.</p>
          )}
        </div>
      )}

      {loading ? (
        <p className="ops-mono text-sm text-[#f3b562]">Computing routes…</p>
      ) : (
        <button
          type="button"
          onClick={computeRoutes}
          disabled={!blockedRoads.trim()}
          className="ops-button ops-button-primary w-full"
        >
          Compute alternate routes
        </button>
      )}
    </div>
  );
};
