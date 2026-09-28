import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import LiveMapCanvas from "../components/LiveMapCanvas";
import { PageHeader, MiniStat } from "../components/ui";

const { Radio, RefreshCw } = Icons;

export function LiveMap({ mapLayer, setMapLayer, notify }: any) {
  const data = useConsoleData();
  const { markers, freshness, zoneStats, zoneName, zone, feedHealth, incidents, reports, resources, predictions } = data;
  const [visibility, setVisibility] = useState({
    floodExtent: true,
    predictionCone: true,
    citizenReports: true,
    teamPositions: true,
    shelters: true,
    incidents: true,
  });
  const zoneCoords = zone
    ? `${Math.abs(zone.centroid_lat).toFixed(1)}°${zone.centroid_lat >= 0 ? "N" : "S"} / ${Math.abs(zone.centroid_lng).toFixed(1)}°${zone.centroid_lng >= 0 ? "E" : "W"}`
    : null;
  const controls = [
    ["Flood extent", "floodExtent"],
    ["Prediction cone", "predictionCone"],
    ["Citizen reports", "citizenReports"],
    ["Team positions", "teamPositions"],
    ["Shelters", "shelters"],
    ["Incidents", "incidents"],
  ] as const;
  return <><PageHeader eyebrow="Operations / Live Map" title="Live operational map" description="Unified view of predicted risk, verified incidents, field teams, shelters and recommended movement."><span className="chip"><Radio size={12} className="text-success"/> {feedHealth.streamLabel}</span><button onClick={()=>{data.refreshAll(); notify("Live map data refreshed");}} className="icon-btn"><RefreshCw size={16}/></button></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]"><div className="panel overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3"><div className="flex gap-1 rounded-lg border border-line bg-slate-950/40 p-1">{["Risk","Routes","Teams","Shelters"].map(l=><button key={l} onClick={()=>setMapLayer(l)} className={`rounded-md px-3 py-1.5 text-[10px] ${mapLayer===l?"bg-slate-700 text-white":"text-slate-500"}`}>{l}</button>)}</div><span className="text-[10px] text-slate-500">{zoneName}{zoneCoords ? ` · ${zoneCoords}` : ""} · {freshness} freshness</span></div><LiveMapCanvas mapLayer={mapLayer} markers={markers} freshness={freshness} zone={zone} incidents={incidents} reports={reports} resources={resources} floodCells={predictions?.last_flood?.affected_cells ?? []} visibility={visibility} /></div><section className="space-y-4"><div className="panel p-4"><p className="eyebrow">Map controls</p><p className="mt-1 text-[10px] text-slate-500">Layers update from the backend feed and polling.</p><div className="mt-3 space-y-2">{controls.map(([label,key])=><button key={key} type="button" onClick={()=>setVisibility(v=>({...v,[key]:!v[key]}))} className="flex w-full items-center justify-between rounded-lg border border-line bg-slate-950/30 px-3 py-2.5 text-left"><span className="text-xs text-slate-300">{label}</span><span className={`h-4 w-7 rounded-full p-0.5 transition ${visibility[key]?"bg-cyan/40":"bg-slate-700"}`}><span className={`block h-3 w-3 rounded-full bg-white transition ${visibility[key]?"ml-3":"ml-0"}`}/></span></button>)}</div></div><div className="panel p-4"><p className="eyebrow">Selected zone</p><h2 className="mt-1 text-sm font-semibold">{zoneName}</h2><div className="mt-3 grid grid-cols-2 gap-2"><MiniStat label="Risk" value={zoneStats.risk}/><MiniStat label="ETA" value={zoneStats.eta}/><MiniStat label="People" value={zoneStats.people}/><MiniStat label="Confidence" value={zoneStats.confidence}/></div><button onClick={()=>setMapLayer("Risk")} className="mt-3 w-full rounded-lg bg-cyan py-2 text-[11px] font-bold text-[#04101b]">Focus risk layer</button></div></section></div></>;
}
