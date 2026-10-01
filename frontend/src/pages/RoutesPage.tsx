import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import LiveMapCanvas from "../components/LiveMapCanvas";
import { PageHeader, PanelTitle } from "../components/ui";
import { routeEngineLabel, toRouteRows } from "../lib/mappers";
import type { RoutesResponse } from "../lib/types";

const { Navigation, RefreshCw, Route, Loader2, Copy } = Icons;

const HAZARDS = [
  { id: "flood", label: "Flood" },
  { id: "earthquake", label: "Earthquake" },
  { id: "cyclone", label: "Cyclone / storm" },
  { id: "fire", label: "Fire" },
  { id: "landslide", label: "Landslide" },
];

/**
 * Route intelligence.
 *
 * The controls drive the real `POST /api/routes/compute` contract: hazard type
 * and blocked-road labels are sent to the planner and the returned corridors
 * replace the polled ones. Every number on this page comes back from that
 * response — the previous build showed a fixed "11 minutes saved" sentence that
 * was not computed from anything.
 */
export function RoutesPage({ notify, setActiveNav }: any) {
  const { routeRows, zone, incidents, resources, reports, predictions } = useConsoleData();

  const [hazard, setHazard] = useState("flood");
  const [blocked, setBlocked] = useState("");
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState<RoutesResponse | null>(null);

  // A manual computation is authoritative until the next poll refreshes it.
  const rows = manual ? toRouteRows(manual) : routeRows;
  const insight = insightFrom(manual);

  const recompute = async () => {
    if (!zone || busy) return;
    setBusy(true);
    try {
      const result = await api.computeRoutes({
        zone_id: zone.zone_id,
        blocked_roads: blocked.trim(),
        disaster_type: hazard,
      });
      setManual(result);
      notify(`Routes recomputed for ${result.zone_name}`);
    } catch {
      notify("Route engine did not respond");
    } finally {
      setBusy(false);
    }
  };

  const share = async () => {
    const summary = rows
      .map((r: any) => `${r.name} — ${r.status}, ${r.eta} (${r.detail})`)
      .join("\n");
    if (!summary) return notify("No computed corridors to share");
    try {
      await navigator.clipboard.writeText(summary);
      notify("Route briefing copied to clipboard");
    } catch {
      notify("Clipboard unavailable — see the corridor list below");
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Operations / Routes"
        title="Route intelligence"
        description="Continuously updated movement corridors for rescue, medical and relief logistics."
      >
        <span className="chip">
          <Navigation size={12} className="text-cyan" />
          {manual ? "Operator routing" : "Routing engine live"}
        </span>
        <button onClick={share} className="icon-btn" title="Copy route briefing">
          <Copy size={15} />
        </button>
      </PageHeader>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_360px]">
        <section className="panel overflow-hidden">
          <div className="h-[310px]">
            <LiveMapCanvas
              mapLayer="Routes"
              markers={[]}
              freshness=""
              zone={zone}
              incidents={incidents}
              resources={resources}
              reports={reports}
              floodCells={predictions?.last_flood?.affected_cells ?? []}
            />
          </div>

          {rows.length === 0 ? (
            <p className="p-4 text-[11px] leading-5 text-slate-500">
              No corridors computed. Run the planner with a hazard type to get a primary route plus
              alternates for this zone.
            </p>
          ) : (
            <div className="divide-y divide-line/70">
              {rows.map((r: any) => (
                <div key={r.name} className="flex items-center gap-3 px-4 py-4">
                  <div
                    className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                      r.status === "CLEAR"
                        ? "bg-success/10 text-success"
                        : r.status === "BLOCKED"
                          ? "bg-danger/10 text-danger"
                          : "bg-amber/10 text-amber"
                    }`}
                  >
                    <Route size={16} />
                  </div>
                  <div className="flex-1">
                    <p className="text-xs font-semibold">{r.name}</p>
                    <p className="mt-1 text-[10px] text-slate-500">{r.detail}</p>
                  </div>
                  <div className="text-right">
                    <p
                      className={`text-[10px] font-bold ${
                        r.status === "CLEAR"
                          ? "text-success"
                          : r.status === "BLOCKED"
                            ? "text-danger"
                            : "text-amber"
                      }`}
                    >
                      {r.status}
                    </p>
                    <p className="text-[10px] text-slate-500">{r.eta}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel p-4">
          <PanelTitle eyebrow="Route controls" title="Mission routing" />

          <div className="mt-4 space-y-3">
            <label className="block text-[10px] text-slate-600">
              Hazard type
              <select
                value={hazard}
                onChange={(e) => setHazard(e.target.value)}
                className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none"
              >
                {HAZARDS.map((h) => (
                  <option key={h.id} value={h.id}>{h.label}</option>
                ))}
              </select>
            </label>

            <label className="block text-[10px] text-slate-600">
              Blocked roads
              <input
                value={blocked}
                onChange={(e) => setBlocked(e.target.value)}
                placeholder="Ashram Road, Ring Road"
                className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none placeholder:text-slate-600"
              />
              <span className="mt-1 block text-[9px] text-slate-600">
                Comma-separated labels the planner must avoid.
              </span>
            </label>

            <button
              onClick={recompute}
              disabled={busy || !zone}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-cyan py-2.5 text-xs font-bold text-[#04101b] disabled:opacity-50"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {busy ? "Routing…" : "Compute routes"}
            </button>
          </div>

          <div className="mt-4 rounded-xl border border-cyan/20 bg-cyan/[.04] p-3">
            <p className="text-[10px] font-semibold text-cyan">Route insight</p>
            <p className="mt-2 text-[11px] leading-5 text-slate-400">
              {insight ??
                "Corridors are computed by the routing engine against live road and hazard costs. Run the planner to compare the primary corridor against its alternates."}
            </p>
          </div>

          <p className="mt-3 text-[9px] text-slate-600">
            Planner: {manual ? routeEngineLabel(manual) : routeEngineLabel(null)}. Corridors are
            suggestions for a human operator, not authorised movements.
          </p>

          <button
            onClick={() => setActiveNav("Teams")}
            className="mt-3 w-full rounded-lg border border-line py-2 text-[11px] font-semibold text-slate-300"
          >
            Share with field teams
          </button>
        </section>
      </div>
    </>
  );
}

/** Real comparison between the primary corridor and the fastest alternate. */
function insightFrom(response: RoutesResponse | null): string | null {
  if (!response) return null;
  const primary = response.primary_route;
  const fastest = response.alternate_routes.reduce<(typeof response.alternate_routes)[number] | null>(
    (best, leg) => (best === null || leg.estimated_minutes < best.estimated_minutes ? leg : best),
    null,
  );
  if (!fastest) {
    return `Primary corridor runs ${primary.distance_km} km in about ${primary.estimated_minutes} min. No alternate was generated for this hazard.`;
  }
  const delta = primary.estimated_minutes - fastest.estimated_minutes;
  const faster = delta > 0 ? `the primary is ${delta} min slower` : delta < 0 ? `the primary is ${Math.abs(delta)} min quicker` : "both take the same time";
  return `Primary corridor: ${primary.distance_km} km in ~${primary.estimated_minutes} min. Against the fastest alternate (${fastest.distance_km} km, ~${fastest.estimated_minutes} min), ${faster}.`;
}
