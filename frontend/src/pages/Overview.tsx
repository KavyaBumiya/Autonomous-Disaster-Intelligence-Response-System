import { useEffect } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { EMPTY_MARKERS } from "../lib/fallbacks";
import LiveMapCanvas from "../components/LiveMapCanvas";
import { PageHeader, Metric, Recommendation } from "../components/ui";

const { Search, RefreshCw, SlidersHorizontal, X, Siren, Zap, Users, Truck, AlertTriangle, ChevronRight, Bot, CircleHelp, Clock3, Layers3, MapPin, Navigation } = Icons;

export function Overview(p: any) {
  const { setActiveNav, alertOpen, setAlertOpen, selectedAlert, setSelectedAlert, mapLayer, setMapLayer, filteredAlerts, query, setQuery, notify, refreshAll, filtersOpen, setFiltersOpen } = p;
  const data = useConsoleData();
  const { kpis, freshness, dashboardAI } = data;
  useEffect(() => {
    if (dashboardAI.activeEmergency) setAlertOpen(true);
  }, [dashboardAI.activeEmergency, setAlertOpen]);
  return <>
    <PageHeader eyebrow="Command center / Overview" title="Situation overview">
      <div className="relative hidden sm:block"><Search size={14} className="absolute left-3 top-2.5 text-slate-500"/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search incident, place..." className="h-9 w-56 rounded-lg border border-line bg-slate-950/50 pl-9 pr-3 text-xs outline-none placeholder:text-slate-600 focus:border-cyan/40"/></div>
      <button onClick={refreshAll} className="icon-btn"><RefreshCw size={16}/></button><button onClick={() => setFiltersOpen(!filtersOpen)} className="icon-btn"><SlidersHorizontal size={16}/></button>
    </PageHeader>
    {filtersOpen && (
      <div className="mb-4 rounded-xl border border-line bg-[#0a1726] p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-bold">Filters</p>
          <button onClick={() => setFiltersOpen(false)} className="text-slate-500 hover:text-white"><X size={14}/></button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {["All incidents", "Critical only", "Active", "Verified"].map(f => (
            <button key={f} onClick={() => notify(`Filter: ${f}`)} className="rounded-lg border border-line bg-slate-950/40 px-3 py-1.5 text-[10px] text-slate-300 hover:border-cyan/30">{f}</button>
          ))}
        </div>
      </div>
    )}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric icon={Siren} label="Active incidents" value={String(kpis.activeIncidents).padStart(2, "0")} sub={`${kpis.criticalIncidents} critical`} tone="danger"/><Metric icon={Zap} label="Prediction confidence" value={kpis.predictionConfidence} sub={kpis.predictionSub} tone="cyan"/><Metric icon={Users} label="People at risk" value={kpis.peopleAtRisk} sub={kpis.peopleAtRiskSub} tone="amber"/><Metric icon={Truck} label="Units deployed" value={kpis.unitsDeployed} sub={kpis.unitsDeployedSub} tone="success"/>
    </div>
    <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_360px]">
      <MapCard mapLayer={mapLayer} setMapLayer={setMapLayer} markers={data.markers} freshness={freshness} feeds={data.feedHealth.streamLabel} zone={data.zone} incidents={data.incidents} resources={data.resources} reports={data.reports}/>
      <aside className="space-y-4">
        {dashboardAI.activeEmergency && alertOpen && <section className="rounded-2xl border border-danger/30 bg-danger/[.07] p-4 shadow-[0_0_30px_rgba(255,92,105,.07)]"><div className="flex items-start justify-between"><div className="flex items-center gap-2"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-danger/10 text-danger"><AlertTriangle size={17}/></div><div><p className="eyebrow !text-danger">AI priority alert</p><p className="mt-0.5 text-sm font-bold">{dashboardAI.title}</p></div></div><button onClick={() => setAlertOpen(false)} className="text-slate-500 hover:text-white"><X size={15}/></button></div><p className="mt-3 text-xs leading-5 text-slate-300">{dashboardAI.summary}</p><div className="mt-3 flex items-center gap-2"><span className="chip !border-danger/20 !text-danger">AI prompted</span><span className="chip">Live context</span></div><button onClick={() => setActiveNav("Incidents")} className="mt-4 flex w-full items-center justify-between rounded-lg bg-danger px-3 py-2.5 text-xs font-bold text-white">Open incident response <ChevronRight size={15}/></button></section>}
        <section className="panel p-4"><div className="mb-3 flex items-center justify-between"><div><p className="eyebrow">AI preparations</p><h2 className="mt-1 text-sm font-semibold">{dashboardAI.activeEmergency ? "Suggested preparations" : "No Emergency Yet"}</h2></div><Bot size={18} className="text-cyan"/></div>{dashboardAI.activeEmergency && dashboardAI.preparations.length > 0 ? <div className="space-y-2">{dashboardAI.preparations.map((text, i) => <Recommendation key={`${text}-${i}`} n={String(i + 1).padStart(2, "0")} text={text} confidence="AI" onClick={() => setActiveNav("AI Assistant")}/>)}</div> : <p className="rounded-xl border border-line bg-slate-950/30 p-3 text-[11px] leading-5 text-slate-500">AegisAI has not prompted an emergency response for the selected zone. No preparations are being invented.</p>}<button onClick={() => setActiveNav("AI Assistant")} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-line py-2 text-[11px] font-semibold text-slate-300">Open AegisAI <ChevronRight size={13}/></button></section>
        <ResourceMini onView={() => setActiveNav("Resources")}/>
      </aside>
    </div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2"><IncidentMini alerts={filteredAlerts} selected={selectedAlert} setSelected={setSelectedAlert} onView={() => setActiveNav("Incidents")}/><RouteMini onView={() => setActiveNav("Routes")}/></div>
    <div className="mt-4 rounded-2xl border border-line bg-[#0a1726] px-4 py-3"><div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-500"><span className="flex items-center gap-1.5"><CircleHelp size={12}/> AI recommendations are decision support, not autonomous commands.</span><span className="hidden text-slate-700 sm:block">•</span><span className="flex items-center gap-1.5"><Clock3 size={12}/> Data freshness: {freshness}</span><span className="hidden text-slate-700 sm:block">•</span><span className="flex items-center gap-1.5"><Layers3 size={12}/> Sources: satellite · citizen reports · field teams</span></div></div>
  </>;
}

function MapCard({ mapLayer, setMapLayer, markers, freshness, feeds, zone, incidents, resources, reports }: any) {
  return <section className="panel overflow-hidden"><div className="flex items-center justify-between border-b border-line px-4 py-3"><div className="flex items-center gap-2"><MapPin size={15} className="text-cyan"/><h2 className="text-sm font-semibold">Live operational map</h2><span className="chip"><span className="h-1.5 w-1.5 rounded-full bg-success"/> {feeds}</span></div><div className="flex rounded-lg border border-line bg-slate-950/40 p-1">{["Risk","Routes","Teams"].map(layer => <button key={layer} onClick={() => setMapLayer(layer)} className={`rounded-md px-2.5 py-1.5 text-[10px] ${mapLayer === layer ? "bg-slate-700 text-white" : "text-slate-500"}`}>{layer}</button>)}</div></div><LiveMapCanvas mapLayer={mapLayer} markers={markers} freshness={freshness} zone={zone} incidents={incidents} resources={resources} reports={reports}/></section>;
}

function MapCanvas({ mapLayer, markers, freshness }: { mapLayer: string; markers?: any; freshness?: string }) {
  // No live markers means the map is genuinely empty. Rendering placeholder
  // pins here would put four coloured dots on a blank map with no way to tell
  // they were invented.
  const pins = Array.isArray(markers) ? markers : EMPTY_MARKERS;
  return <div className="relative h-[420px] overflow-hidden map-grid bg-[#091827]"><svg viewBox="0 0 900 520" className="absolute inset-0 h-full w-full"><g opacity=".25" stroke="#7890a8" fill="none" strokeWidth="2"><path d="M50 85 L260 110 L380 55 L560 120 L820 70"/><path d="M10 190 L210 170 L360 235 L540 205 L890 260"/><path d="M20 350 L180 290 L350 330 L510 290 L720 360 L900 320"/><path d="M160 20 L190 500"/><path d="M330 0 L390 520"/><path d="M520 0 L490 520"/><path d="M700 0 L660 520"/></g><g opacity=".32" stroke="#39d9ff" fill="none" strokeWidth="6"><path d="M35 430 C180 320 180 150 340 190 S590 370 865 120"/></g><path className="route" d="M60 420 C190 320 220 220 360 250 S570 350 810 150" fill="none" stroke="#35d39a" strokeWidth="5" strokeLinecap="round"/>{pins.map((p:any,i:number)=><g key={i}><circle cx={p.x} cy={p.y} r="18" fill={p.c} opacity=".12" className={i===0 ? "pulse" : ""}/><circle cx={p.x} cy={p.y} r="7" fill={p.c}/><rect x={p.x+12} y={p.y-12} rx="5" width="64" height="20" fill="#07111f" opacity=".9"/><text x={p.x+22} y={p.y+2} fill={p.c} fontSize="9" fontWeight="700">{p.label}</text></g>)}</svg><div className="absolute bottom-3 left-3 flex flex-wrap gap-2"><span className="chip"><span className="h-2 w-2 rounded-full bg-danger"/> Critical</span><span className="chip"><span className="h-2 w-2 rounded-full bg-amber"/> Warning</span><span className="chip"><span className="h-2 w-2 rounded-full bg-cyan"/> Shelter</span><span className="chip"><span className="h-2 w-2 rounded-full bg-success"/> Safe route</span></div><div className="absolute right-3 top-3 rounded-lg border border-line bg-[#07111f]/90 px-3 py-2 text-[10px] text-slate-400">{mapLayer} layer · Updated {freshness ?? "8"} sec ago</div></div>;
}

function IncidentMini({ alerts, selected, setSelected, onView }: any) {
  return <section className="panel"><div className="flex items-center justify-between border-b border-line px-4 py-3"><div><p className="eyebrow">Incident feed</p><h2 className="mt-1 text-sm font-semibold">Verified signals</h2></div><button onClick={onView} className="text-[10px] font-semibold text-cyan">View all</button></div><div className="divide-y divide-line/70">{alerts.slice(0,4).map((a:any)=><button key={a.id} onClick={() => setSelected(a)} className={`flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-900/50 ${selected?.id===a.id?"bg-cyan/[.035]":""}`}><div className={`h-2.5 w-2.5 rounded-full ${a.level==="CRITICAL"?"bg-danger":"bg-amber"}`}/><div className="min-w-0 flex-1"><p className="text-xs font-semibold text-white">{a.title}</p><p className="mt-0.5 truncate text-[10px] text-slate-500">{a.place} · {a.time}</p></div><span className="text-[10px] font-semibold text-slate-400">{a.confidence}%</span><ChevronRight size={14} className="text-slate-600"/></button>)}</div></section>;
}

function RouteMini({ onView }: any) {
  const { routeRows } = useConsoleData();
  return <section className="panel"><div className="flex items-center justify-between border-b border-line px-4 py-3"><div><p className="eyebrow">Route intelligence</p><h2 className="mt-1 text-sm font-semibold">Recommended movement</h2></div><button onClick={onView} className="text-[10px] font-semibold text-cyan">View all</button></div><div className="divide-y divide-line/70">{routeRows.slice(0,3).map(r=><div key={r.name} className="flex items-center gap-3 px-4 py-3"><div className={`flex h-8 w-8 items-center justify-center rounded-lg ${r.status==="CLEAR"?"bg-success/10 text-success":r.status==="BLOCKED"?"bg-danger/10 text-danger":"bg-amber/10 text-amber"}`}><Navigation size={14}/></div><div className="min-w-0 flex-1"><p className="text-xs font-semibold text-slate-200">{r.name}</p><p className="mt-0.5 text-[10px] text-slate-500">{r.detail}</p></div><div className="text-right"><p className={`text-[10px] font-bold ${r.status==="CLEAR"?"text-success":r.status==="BLOCKED"?"text-danger":"text-amber"}`}>{r.status}</p><p className="mt-0.5 text-[10px] text-slate-500">{r.eta}</p></div></div>)}</div></section>;
}

function ResourceMini({ onView }: any) {
  const { resourceCards } = useConsoleData();
  return <section className="panel p-4"><div className="mb-3 flex items-center justify-between"><div><p className="eyebrow">Resources</p><h2 className="mt-1 text-sm font-semibold">Operational capacity</h2></div><button onClick={onView} className="text-[10px] font-semibold text-cyan">View all</button></div><div className="space-y-3">{resourceCards.map((r:any)=>{const Icon=r.icon;const pct=Math.round(r.value/r.total*100);return <div key={r.label}><div className="flex items-center gap-2 text-[11px]"><Icon size={13} className="text-slate-500"/><span className="flex-1 text-slate-300">{r.label}</span><span className="font-semibold text-white">{r.value}</span><span className="text-slate-600">/ {r.total}</span></div><div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800"><div className={`h-full rounded-full ${pct<60?"bg-danger":"bg-cyan"}`} style={{width:`${pct}%`}}/></div></div>})}</div></section>;
}