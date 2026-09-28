import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, Bell, Bot, CheckCircle2, ChevronRight, CircleHelp,
  Clock3, Crosshair, FileWarning, Gauge, HeartPulse, Layers3, MapPin, Menu,
  MessageSquare, Navigation, Package, Radio, RefreshCw, Search, Settings2,
  Shield, Siren, SlidersHorizontal, Truck, Users, X, Zap, Route, Satellite,
  BrainCircuit, ClipboardCheck, Send, ArrowUpRight, MapPinned, TimerReset
} from "lucide-react";
import {
  ConsoleDataProvider, useConsoleData, type ConsoleVisuals, type ResourceSlotVisual
} from "./lib/consoleData";
import { api } from "./lib/api";
import { useAssistant } from "./lib/useAssistant";
import { FALLBACK_MARKERS } from "./lib/fallbacks";
import LiveMapCanvas from "./components/LiveMapCanvas";

type Role = "Command" | "Rescue" | "NGO";
type NavItem = "Overview" | "Live Map" | "Incidents" | "Resources" | "Routes" | "Teams" |
  "Prediction Engine" | "Resource Commander" | "AI Assistant";

/* ── Visual vocabulary (unchanged design; only values are data-driven) ────── */

const RESOURCE_SLOTS: readonly ResourceSlotVisual<typeof Users>[] = [
  { id: "teams", label: "Rescue teams", icon: Users, unit: "teams" },
  { id: "vehicles", label: "Ambulances", icon: HeartPulse, unit: "vehicles" },
  { id: "food", label: "Food kits", icon: Package, unit: "kits" },
  { id: "water", label: "Water units", icon: Activity, unit: "units" },
];

const VISUALS: ConsoleVisuals = {
  resourceSlots: RESOURCE_SLOTS,
  evidenceLabels: [
    "River sensor trend",
    "Satellite moisture anomaly",
    "CCTV waterline detection",
    "Citizen reports",
    "Weather nowcast",
  ],
  constraintTitles: ["Ambulance availability", "Rescue team coverage", "Water reserve", "Fuel stock"],
  pressureLabels: ["Water", "Medical kits", "Food", "Fuel"],
  pressureNotes: ["Reserve 180 units", "Stable", "Restock in 4 hr", "Priority replenishment"],
};

const INITIAL_ASSISTANT_MESSAGES: Array<{ who: "ai" | "user"; text: string }> = [];

/** Per-slot confirmation toasts, preserved from the original recommendations. */
const RECOMMENDATION_TOASTS = [
  "Action added to review queue",
  "Route review opened",
  "Resource reservation drafted",
];

/** Per-slot confirmations for the resources allocation queue. */
const ALLOCATION_TOASTS = ["Allocation 1 approved", "Allocation 2 approved", "Allocation 3 approved", "Allocation 4 approved"];

/**
 * Root: supplies the console's visual vocabulary and exposes live data to the
 * tree. Renders no DOM of its own, so the markup below is unchanged.
 */
function App() {
  return (
    <ConsoleDataProvider visuals={VISUALS}>
      <Console />
    </ConsoleDataProvider>
  );
}

function Console() {
  const data = useConsoleData();
  const [role, setRole] = useState<Role>("Command");
  const [activeNav, setActiveNav] = useState<NavItem>("Overview");
  const [selectedAlert, setSelectedAlert] = useState(data.alerts[0] ?? null);
  const [alertOpen, setAlertOpen] = useState(true);
  const [aiOpen, setAiOpen] = useState(true);
  const [mapLayer, setMapLayer] = useState("Risk");
  const [toast, setToast] = useState("");
  const [query, setQuery] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const alerts = data.alerts;

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2400);
  };

  /** Refresh every panel, then reuse the console's existing toast. */
  const refreshAll = () => {
    data.refreshAll();
    notify("Dashboard data refreshed");
  };

  const nav: { label: NavItem; icon: any; count?: number; section?: string }[] = [
    { label: "Overview", icon: Gauge },
    { label: "Live Map", icon: MapPin },
    { label: "Incidents", icon: Siren, count: data.kpis.activeIncidents },
    { label: "Resources", icon: Package },
    { label: "Routes", icon: Navigation },
    { label: "Teams", icon: Users },
    { label: "Prediction Engine", icon: Bot, section: "AI systems" },
    { label: "Resource Commander", icon: Crosshair },
    { label: "AI Assistant", icon: MessageSquare },
  ];

  const filteredAlerts = useMemo(
    () => alerts.filter(a => `${a.title} ${a.place}`.toLowerCase().includes(query.toLowerCase())),
    [alerts, query]
  );

  const openNav = (item: NavItem) => {
    setActiveNav(item);
    setQuery("");
  };

  return (
    <div className="min-h-screen bg-[#07111f]">
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-line bg-[#081321]/95 px-4 backdrop-blur-xl lg:px-6">
        <div className="flex items-center gap-3">
          <button onClick={() => setMobileNavOpen(!mobileNavOpen)} className="icon-btn lg:hidden"><Menu size={18}/></button>
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan/10 ring-1 ring-cyan/30"><Shield size={19} className="text-cyan"/></div>
          <div>
            <div className="flex items-center gap-2"><span className="text-sm font-bold tracking-tight">AEGIS<span className="text-cyan">AI</span></span><span className="rounded bg-success/10 px-1.5 py-0.5 text-[9px] font-bold text-success ring-1 ring-success/20">LIVE</span></div>
            <p className="hidden text-[10px] text-slate-500 sm:block">Integrated Disaster Command System</p>
          </div>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <div className="flex rounded-xl border border-line bg-slate-950/50 p-1">
            {(["Command","Rescue","NGO"] as Role[]).map(r => <button key={r} onClick={() => setRole(r)} className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${role === r ? "bg-cyan/10 text-cyan" : "text-slate-500 hover:text-slate-200"}`}>{r}</button>)}
          </div>
          <span className="chip"><Radio size={12} className="text-success"/> {data.feedHealth.statusLabel}</span>
          <button onClick={() => setNotifOpen(!notifOpen)} className="icon-btn"><Bell size={17}/></button>
          <div className="ml-1 flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-bold">OC</div>
        </div>
      </header>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileNavOpen(false)} />
          <div className="absolute left-0 top-0 h-full w-64 border-r border-line bg-[#081321] p-4 shadow-2xl">
            <div className="mb-6 flex items-center justify-between">
              <span className="text-sm font-bold tracking-tight">AEGIS<span className="text-cyan">AI</span></span>
              <button onClick={() => setMobileNavOpen(false)} className="text-slate-500 hover:text-white"><X size={18}/></button>
            </div>
            <nav className="space-y-1">
              {nav.map((item) => {
                const Icon = item.icon;
                return <button key={item.label} onClick={() => { openNav(item.label); setMobileNavOpen(false); }} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs transition ${activeNav === item.label ? "bg-cyan/10 text-cyan ring-1 ring-cyan/15" : "text-slate-400 hover:bg-slate-900/60 hover:text-white"}`}>
                  <Icon size={16}/><span className="flex-1">{item.label}</span>
                </button>;
              })}
            </nav>
          </div>
        </div>
      )}

      {notifOpen && (
        <div className="fixed right-4 top-16 z-40 w-72 rounded-xl border border-line bg-[#0b1828] p-4 shadow-2xl">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold">Notifications</p>
            <button onClick={() => setNotifOpen(false)} className="text-slate-500 hover:text-white"><X size={14}/></button>
          </div>
          <p className="mt-3 text-[11px] text-slate-400">No new notifications</p>
        </div>
      )}

      <div className="flex">
        <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] w-56 shrink-0 border-r border-line bg-[#081321] p-3 lg:block">
          <div className="mb-5 px-2 pt-2"><p className="eyebrow">Operations</p><p className="mt-1 text-xs text-slate-500">Ahmedabad · Incident 24-091</p></div>
          <nav className="space-y-1">
            {nav.map((item, i) => {
              const Icon = item.icon;
              return <div key={item.label}>
                {item.section && <p className="mb-2 mt-5 px-2 text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500">{item.section}</p>}
                <button onClick={() => openNav(item.label)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs transition ${activeNav === item.label ? "bg-cyan/10 text-cyan ring-1 ring-cyan/15" : "text-slate-400 hover:bg-slate-900/60 hover:text-white"}`}>
                  <Icon size={16}/><span className="flex-1">{item.label}</span>{item.count && <span className="rounded-md bg-danger/10 px-1.5 py-0.5 text-[9px] font-bold text-danger">{item.count}</span>}
                </button>
              </div>
            })}
          </nav>
          <div className="absolute bottom-4 left-3 right-3 rounded-xl border border-line bg-slate-950/40 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold"><div className="h-2 w-2 rounded-full bg-success"/><span>{data.feedHealth.systemLabel}</span></div>
            <p className="mt-1 text-[10px] text-slate-500">Last sync {data.freshness} ago · {data.feedHealth.sourceCount} sources</p>
          </div>
        </aside>

        <main className="min-w-0 flex-1 p-4 lg:p-6">
          <div className="mx-auto max-w-[1600px]">
            {activeNav === "Overview" && <Overview {...{setActiveNav: openNav, alertOpen, setAlertOpen, selectedAlert, setSelectedAlert, aiOpen, setAiOpen, mapLayer, setMapLayer, filteredAlerts, query, setQuery, notify, refreshAll, filtersOpen, setFiltersOpen}} />}
            {activeNav === "Live Map" && <LiveMap mapLayer={mapLayer} setMapLayer={setMapLayer} notify={notify}/>}
            {activeNav === "Incidents" && <Incidents alerts={filteredAlerts} selected={selectedAlert} setSelected={setSelectedAlert} query={query} setQuery={setQuery} notify={notify} refreshAll={refreshAll}/>}
{activeNav === "Resources" && <Resources notify={notify} setActiveNav={openNav}/>}
             {activeNav === "Routes" && <RoutesPage notify={notify} refreshAll={refreshAll} setActiveNav={openNav}/>}
             {activeNav === "Teams" && <TeamsPage notify={notify} setActiveNav={openNav}/>}
            {activeNav === "Prediction Engine" && <PredictionPage notify={notify} refreshAll={refreshAll}/>}
            {activeNav === "Resource Commander" && <CommanderPage notify={notify}/>}
            {activeNav === "AI Assistant" && <AssistantPage role={role} notify={notify}/>}
          </div>
        </main>
      </div>

      {toast && <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-line bg-[#0b1828] px-4 py-2.5 text-xs font-semibold text-slate-200 shadow-2xl">{toast}</div>}
    </div>
  );
}

function PageHeader({ eyebrow, title, description, action, children }: any) {
  return <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
    <div><p className="eyebrow">{eyebrow}</p><h1 className="mt-1 text-xl font-bold tracking-tight text-white md:text-2xl">{title}</h1>{description && <p className="mt-1 max-w-2xl text-xs text-slate-500">{description}</p>}</div>
    <div className="flex items-center gap-2">{children}{action}</div>
  </div>;
}

function Metric({ icon: Icon, label, value, sub, tone }: { icon: any; label: string; value: string; sub: string; tone: "danger"|"cyan"|"amber"|"success" }) {
  const tones = { danger: "text-danger bg-danger/10", cyan: "text-cyan bg-cyan/10", amber: "text-amber bg-amber/10", success: "text-success bg-success/10" };
  return <div className="panel p-4"><div className="flex items-center gap-3"><div className={`flex h-9 w-9 items-center justify-center rounded-lg ${tones[tone]}`}><Icon size={17}/></div><div className="min-w-0"><p className="eyebrow">{label}</p><p className="mt-0.5 text-xl font-bold tracking-tight">{value}</p></div></div><p className="mt-3 text-[10px] text-slate-500">{sub}</p></div>;
}

function Recommendation({ n, text, confidence, onClick }: any) {
  return <button onClick={onClick} className="w-full rounded-xl border border-line bg-slate-950/30 p-3 text-left transition hover:border-cyan/20 hover:bg-cyan/[.025]"><div className="flex gap-3"><span className="font-mono text-[10px] text-cyan/70">{n}</span><div className="flex-1"><p className="text-[11px] leading-4 text-slate-200">{text}</p><p className="mt-1.5 text-[9px] text-slate-500">Confidence {confidence} · explainable</p></div><ChevronRight size={13} className="mt-0.5 text-slate-600"/></div></button>;
}

function Overview(p: any) {
  const { setActiveNav, alertOpen, setAlertOpen, selectedAlert, setSelectedAlert, aiOpen, setAiOpen, mapLayer, setMapLayer, filteredAlerts, query, setQuery, notify, refreshAll, filtersOpen, setFiltersOpen } = p;
  const data = useConsoleData();
  const { kpis, priorityAlert, recommendations, freshness } = data;
  const assistant = useAssistantQuickQuery(notify, data.zoneId);
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
      <MapCard mapLayer={mapLayer} setMapLayer={setMapLayer} markers={data.markers} freshness={freshness} feeds={data.feedHealth.streamLabel}/>
      <aside className="space-y-4">
        {alertOpen && <section className="rounded-2xl border border-danger/30 bg-danger/[.07] p-4 shadow-[0_0_30px_rgba(255,92,105,.07)]"><div className="flex items-start justify-between"><div className="flex items-center gap-2"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-danger/10 text-danger"><AlertTriangle size={17}/></div><div><p className="eyebrow !text-danger">Priority alert</p><p className="mt-0.5 text-sm font-bold">{priorityAlert.title}</p></div></div><button onClick={() => setAlertOpen(false)} className="text-slate-500 hover:text-white"><X size={15}/></button></div><p className="mt-3 text-xs leading-5 text-slate-300">AI predicts risk escalation in <b className="text-white">{priorityAlert.etaMinutes} min</b>. {priorityAlert.people} people fall inside the projected impact zone.</p><div className="mt-3 flex items-center gap-2"><span className="chip !border-danger/20 !text-danger">{priorityAlert.confidence} confidence</span><span className="chip">{priorityAlert.evidenceStreams} evidence streams</span></div><button onClick={() => setActiveNav("Routes")} className="mt-4 flex w-full items-center justify-between rounded-lg bg-danger px-3 py-2.5 text-xs font-bold text-white">Open response plan <ChevronRight size={15}/></button></section>}
        <section className="panel p-4"><div className="mb-3 flex items-center justify-between"><div><p className="eyebrow">AI recommendations</p><h2 className="mt-1 text-sm font-semibold">Next best actions</h2></div><Bot size={18} className="text-cyan"/></div><div className="space-y-2">{recommendations.map((r, i) => <Recommendation key={r.text} n={String(i + 1).padStart(2, "0")} text={r.text} confidence={r.confidence} onClick={() => notify(RECOMMENDATION_TOASTS[i] ?? "Action added to review queue")}/>)}</div><button onClick={() => setActiveNav("AI Assistant")} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-line py-2 text-[11px] font-semibold text-slate-300">Ask AegisAI about this <ChevronRight size={13}/></button></section>
        <ResourceMini onView={() => setActiveNav("Resources")}/>
      </aside>
    </div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2"><IncidentMini alerts={filteredAlerts} selected={selectedAlert} setSelected={setSelectedAlert} onView={() => setActiveNav("Incidents")}/><RouteMini onView={() => setActiveNav("Routes")}/></div>
    <div className="mt-4 rounded-2xl border border-line bg-[#0a1726] px-4 py-3"><div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-500"><span className="flex items-center gap-1.5"><CircleHelp size={12}/> AI recommendations are decision support, not autonomous commands.</span><span className="hidden text-slate-700 sm:block">•</span><span className="flex items-center gap-1.5"><Clock3 size={12}/> Data freshness: {freshness}</span><span className="hidden text-slate-700 sm:block">•</span><span className="flex items-center gap-1.5"><Layers3 size={12}/> Sources: satellite · CCTV · citizen reports · field teams</span></div></div>
    {aiOpen ? <div className="fixed bottom-4 right-4 z-40 w-[calc(100vw-2rem)] max-w-[360px]"><div className="rounded-2xl border border-cyan/20 bg-[#0a1726]/95 p-3 shadow-2xl backdrop-blur-xl"><div className="flex items-center gap-2"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan/10 text-cyan"><Bot size={17}/></div><div className="flex-1"><p className="text-xs font-bold">Ask AegisAI</p><p className="text-[10px] text-slate-500">Command mode · live context enabled</p></div><button onClick={() => setAiOpen(false)} className="text-slate-500"><X size={15}/></button></div><div className="mt-3 flex items-center gap-2"><input ref={assistant.inputRef} onKeyDown={e => e.key === "Enter" && assistant.submit()} placeholder="e.g. Where should Team 4 go?" className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-slate-950/60 px-3 text-[11px] outline-none placeholder:text-slate-600"/><button onClick={assistant.submit} className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan text-[#04101b]"><ChevronRight size={16}/></button></div></div></div> : <button onClick={() => setAiOpen(true)} className="fixed bottom-4 right-4 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-cyan text-[#04101b] shadow-lg"><Bot size={20}/></button>}
  </>;
}

/**
 * One-shot commander query for the overview's inline prompt. Reuses the same
 * gateway endpoint as the full assistant page. The prompt input stays
 * uncontrolled, so its markup and behaviour are untouched — a ref is all that
 * is needed to read what was typed.
 */
function useAssistantQuickQuery(notify: (s: string) => void, zoneId: string | null) {
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const submit = () => {
    const query = (inputRef.current?.value ?? "").trim();
    if (!query || pending) return;
    if (inputRef.current) inputRef.current.value = "";
    setPending(true);
    void api
      .commandQuery({ user_query: query, include_xai: true, zone_context: zoneId })
      .then(() => notify("AegisAI received your command"))
      .catch(() => notify("AegisAI could not reach the backend"))
      .finally(() => setPending(false));
  };

  return { submit, inputRef };
}

function MapCard({ mapLayer, setMapLayer, markers, freshness, feeds }: any) {
  return <section className="panel overflow-hidden"><div className="flex items-center justify-between border-b border-line px-4 py-3"><div className="flex items-center gap-2"><MapPin size={15} className="text-cyan"/><h2 className="text-sm font-semibold">Live operational map</h2><span className="chip"><span className="h-1.5 w-1.5 rounded-full bg-success"/> {feeds}</span></div><div className="flex rounded-lg border border-line bg-slate-950/40 p-1">{["Risk","Routes","Teams"].map(layer => <button key={layer} onClick={() => setMapLayer(layer)} className={`rounded-md px-2.5 py-1.5 text-[10px] ${mapLayer === layer ? "bg-slate-700 text-white" : "text-slate-500"}`}>{layer}</button>)}</div></div><LiveMapCanvas mapLayer={mapLayer} markers={markers} freshness={freshness} /></section>;
}

function MapCanvas({ mapLayer, markers, freshness }: { mapLayer: string; markers?: any; freshness?: string }) {
  const pins = Array.isArray(markers) && markers.length > 0 ? markers : FALLBACK_MARKERS;
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

function LiveMap({ mapLayer, setMapLayer, notify }: any) {
  const data = useConsoleData();
  const { markers, freshness, zoneStats, zoneName, feedHealth } = data;
  return <><PageHeader eyebrow="Operations / Live Map" title="Live operational map" description="Unified view of predicted risk, verified incidents, field teams, shelters and recommended movement."><span className="chip"><Radio size={12} className="text-success"/> {feedHealth.streamLabel}</span><button onClick={()=>{data.refreshAll(); notify("Map layers refreshed");}} className="icon-btn"><RefreshCw size={16}/></button></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]"><div className="panel overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3"><div className="flex gap-1 rounded-lg border border-line bg-slate-950/40 p-1">{["Risk","Routes","Teams","Shelters"].map(l=><button key={l} onClick={()=>setMapLayer(l)} className={`rounded-md px-3 py-1.5 text-[10px] ${mapLayer===l?"bg-slate-700 text-white":"text-slate-500"}`}>{l}</button>)}</div><span className="text-[10px] text-slate-500">Ahmedabad · 20.2°N / 73.0°E · {freshness} freshness</span></div><LiveMapCanvas mapLayer={mapLayer} markers={markers} freshness={freshness} /></div><section className="space-y-4"><div className="panel p-4"><p className="eyebrow">Map controls</p><div className="mt-3 space-y-2">{["Flood extent","Prediction cone","CCTV coverage","Citizen reports","Team positions"].map((x,i)=><div key={x} className="flex items-center justify-between rounded-lg border border-line bg-slate-950/30 px-3 py-2.5"><span className="text-xs text-slate-300">{x}</span><span className={`h-4 w-7 rounded-full p-0.5 ${i===2?"bg-slate-700":"bg-cyan/30"}`}><span className={`block h-3 w-3 rounded-full bg-white ${i===2?"":"ml-3"}`}/></span></div>)}</div></div><div className="panel p-4"><p className="eyebrow">Selected zone</p><h2 className="mt-1 text-sm font-semibold">{zoneName}</h2><div className="mt-3 grid grid-cols-2 gap-2"><MiniStat label="Risk" value={zoneStats.risk}/><MiniStat label="ETA" value={zoneStats.eta}/><MiniStat label="People" value={zoneStats.people}/><MiniStat label="Confidence" value={zoneStats.confidence}/></div><button onClick={()=>notify("Zone response plan opened")} className="mt-3 w-full rounded-lg bg-cyan py-2 text-[11px] font-bold text-[#04101b]">Open response plan</button></div></section></div></>;
}

function Incidents({ alerts, selected, setSelected, query, setQuery, notify, refreshAll }: any) {
  const data = useConsoleData();
  const incident = data.selectedIncidentFor(selected);
  const [explanation, setExplanation] = useState<string | null>(null);

  // Pull the XAI rationale for whichever incident the operator has selected.
  useEffect(() => {
    let cancelled = false;
    setExplanation(null);
    if (!incident?.incident_id) return undefined;
    void api
      .explain(incident.incident_id)
      .then(result => { if (!cancelled) setExplanation(result.explanation || result.xai_raw || null); })
      .catch(() => { if (!cancelled) setExplanation(null); });
    return () => { cancelled = true; };
  }, [incident?.incident_id]);

  const assessment = explanation ?? incident?.groq_explanation ?? incident?.xai_reasoning ?? "No explanation available for this incident.";

  return <><PageHeader eyebrow="Operations / Incidents" title="Incident command queue" description="Verify, prioritize and assign response actions across incoming disaster signals."><div className="relative"><Search size={14} className="absolute left-3 top-2.5 text-slate-500"/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search incidents..." className="h-9 w-52 rounded-lg border border-line bg-slate-950/50 pl-9 pr-3 text-xs outline-none"/></div><button onClick={()=>{refreshAll(); notify("Incident feed refreshed");}} className="icon-btn"><RefreshCw size={16}/></button></PageHeader><div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]"><section className="panel overflow-hidden"><div className="grid grid-cols-[1.1fr_1fr_.7fr_.7fr_24px] border-b border-line px-4 py-3 text-[10px] uppercase tracking-wider text-slate-600"><span>Incident</span><span>Location</span><span>Confidence</span><span>Status</span><span/></div>{alerts.map((a:any)=><button key={a.id} onClick={()=>setSelected(a)} className={`grid w-full grid-cols-[1.1fr_1fr_.7fr_.7fr_24px] items-center border-b border-line/70 px-4 py-4 text-left hover:bg-slate-900/50 ${selected?.id===a.id?"bg-cyan/[.035]":""}`}><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${a.level==="CRITICAL"?"bg-danger":a.level==="HIGH"?"bg-amber":"bg-cyan"}`}/><div><p className="text-xs font-semibold text-white">{a.title}</p><p className="text-[9px] text-slate-600">{a.id} · {a.time}</p></div></div><span className="text-[11px] text-slate-400">{a.place}</span><span className="text-[11px] font-semibold text-slate-300">{a.confidence}%</span><span className={`text-[10px] font-semibold ${a.status==="Active"?"text-danger":a.status==="Verified"?"text-success":"text-amber"}`}>{a.status}</span><ChevronRight size={14} className="text-slate-600"/></button>)}</section><section className="panel p-4"><p className="eyebrow">Incident detail</p><h2 className="mt-1 text-base font-bold">{selected?.title ?? "No incident selected"}</h2><p className="mt-1 text-xs text-slate-500">{selected?.place ?? "Select an incident to view details"}</p><div className="mt-4 grid grid-cols-2 gap-2"><MiniStat label="Confidence" value={`${selected?.confidence ?? 0}%`}/><MiniStat label="Priority" value={selected?.level ?? "—"}/><MiniStat label="Evidence" value={incident ? `${Math.max(1, Math.round(incident.report_count))} streams` : "3 streams"}/><MiniStat label="Last update" value={selected?.time ?? "—"}/></div><div className="mt-4 rounded-xl border border-line bg-slate-950/30 p-3"><p className="text-[10px] font-semibold text-slate-300">AI assessment</p><p className="mt-2 text-[11px] leading-5 text-slate-400">{assessment}</p></div><button onClick={()=>notify("Response workflow created")} className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-danger py-2.5 text-xs font-bold text-white"><ClipboardCheck size={14}/> Create response workflow</button></section></div></>;
}

function Resources({ notify, setActiveNav }: any) {
  const { resourceCards, allocationQueue, pressure, topIncident, refreshAll } = useConsoleData();
  const [assigning, setAssigning] = useState(false);

  /**
   * Run the deterministic resource commander for the active incident. The
   * approval gate is untouched: this only drafts the allocation.
   */
  const approveAllocation = async (index: number) => {
    if (!topIncident || assigning) return;
    setAssigning(true);
    try {
      await api.assignResources(topIncident.incident_id);
      refreshAll();
      notify(ALLOCATION_TOASTS[index] ?? `Allocation ${index + 1} approved`);
    } catch {
      notify("Allocation could not be drafted — backend unreachable");
    } finally {
      setAssigning(false);
    }
  };

  return <><PageHeader eyebrow="Operations / Resources" title="Resource command" description="Track available capacity and allocate people, vehicles and relief supplies to active incidents."><button onClick={() => setActiveNav("Resource Commander")} className="flex items-center gap-2 rounded-lg bg-cyan px-3 py-2 text-[11px] font-bold text-[#04101b]"><Package size={14}/> New allocation</button></PageHeader><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{resourceCards.map((r:any)=><div key={r.label} className="panel p-4"><div className="flex items-center justify-between"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan/10 text-cyan"><r.icon size={17}/></div><span className="chip">{Math.round(r.value/r.total*100)}%</span></div><p className="mt-4 text-xs text-slate-500">{r.label}</p><p className="mt-1 text-2xl font-bold">{r.value.toLocaleString()}</p><p className="text-[10px] text-slate-600">of {r.total.toLocaleString()} available</p><div className="mt-3 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{width:`${Math.round(r.value/r.total*100)}%`}}/></div></div>)}</div><div className="mt-4 grid gap-4 lg:grid-cols-2"><section className="panel"><PanelTitle eyebrow="Allocation queue" title="Recommended allocations"/><div className="divide-y divide-line/70">{allocationQueue.map((x,i)=><div key={x} className="flex items-center gap-3 px-4 py-4"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan/10 text-cyan">{i+1}</div><p className="flex-1 text-xs text-slate-300">{x}</p><span className="chip">{i<2?"AI recommended":"Queued"}</span><button onClick={()=>approveAllocation(i)} className="icon-btn"><CheckCircle2 size={15}/></button></div>)}</div></section><section className="panel"><PanelTitle eyebrow="Stock health" title="Supply pressure"/><div className="space-y-4 p-4">{pressure.map(p=><Pressure key={p.label} label={p.label} value={p.value} note={p.note}/>)}</div></section></div></>;
}

function RoutesPage({ notify, refreshAll, setActiveNav }: any) {
  const { routeRows } = useConsoleData();
  return <><PageHeader eyebrow="Operations / Routes" title="Route intelligence" description="Continuously updated movement corridors for rescue, medical and relief logistics."><span className="chip"><Navigation size={12} className="text-cyan"/> Routing engine live</span><button onClick={()=>{refreshAll(); notify("Routes recalculated");}} className="icon-btn"><RefreshCw size={16}/></button></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_360px]"><section className="panel overflow-hidden"><div className="h-[310px]"><LiveMapCanvas mapLayer="Routes" markers={[]} freshness="" /></div><div className="divide-y divide-line/70">{routeRows.map(r=><div key={r.name} className="flex items-center gap-3 px-4 py-4"><div className={`flex h-9 w-9 items-center justify-center rounded-lg ${r.status==="CLEAR"?"bg-success/10 text-success":r.status==="BLOCKED"?"bg-danger/10 text-danger":"bg-amber/10 text-amber"}`}><Route size={16}/></div><div className="flex-1"><p className="text-xs font-semibold">{r.name}</p><p className="mt-1 text-[10px] text-slate-500">{r.detail}</p></div><div className="text-right"><p className={`text-[10px] font-bold ${r.status==="CLEAR"?"text-success":r.status==="BLOCKED"?"text-danger":"text-amber"}`}>{r.status}</p><p className="text-[10px] text-slate-500">{r.eta}</p></div><button onClick={() => setActiveNav("Routes")} className="icon-btn"><ArrowUpRight size={14}/></button></div>)}</div></section><section className="panel p-4"><PanelTitle eyebrow="Route controls" title="Mission routing"/><div className="mt-4 space-y-3"><SelectLike label="Mission type" value="Rescue / emergency"/><SelectLike label="Avoid" value="Flood zones + blocked roads"/><SelectLike label="Priority" value="Fastest safe route"/><div className="rounded-xl border border-cyan/20 bg-cyan/[.04] p-3"><p className="text-[10px] font-semibold text-cyan">AI route insight</p><p className="mt-2 text-[11px] leading-5 text-slate-400">North corridor reduces expected response time by 11 minutes while avoiding the predicted flood expansion.</p></div><button onClick={()=>notify("Mission route shared with selected teams")} className="w-full rounded-lg bg-cyan py-2.5 text-xs font-bold text-[#04101b]">Share recommended route</button></div></section></div></>;
}

function TeamsPage({ notify, setActiveNav }: any) {
  const { teamRows, readiness, feedHealth } = useConsoleData();
  // "Comms health" maps to how many of the backend's data providers are
  // actually reachable — the console's own definition of an operator's comms.
  const commsHealth = feedHealth.sourceCount > 0
    ? Math.round((feedHealth.healthyFeeds / feedHealth.sourceCount) * 100)
    : 0;
  return <><PageHeader eyebrow="Operations / Teams" title="Field teams" description="See who is deployed, where they are, what they can do, and how quickly they can respond."><button onClick={()=>notify("Team dispatch panel opened")} className="flex items-center gap-2 rounded-lg bg-cyan px-3 py-2 text-[11px] font-bold text-[#04101b]"><Send size={13}/> Dispatch team</button></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]"><section className="panel overflow-hidden"><div className="grid grid-cols-[1.3fr_1fr_.7fr_.8fr_.6fr_24px] border-b border-line px-4 py-3 text-[10px] uppercase tracking-wider text-slate-600"><span>Team</span><span>Specialty</span><span>People</span><span>Status</span><span>ETA</span><span/></div>{teamRows.map(t=><div key={t.name} className="grid grid-cols-[1.3fr_1fr_.7fr_.8fr_.6fr_24px] items-center border-b border-line/70 px-4 py-4"><div><p className="text-xs font-semibold">{t.name}</p><p className="mt-1 text-[10px] text-slate-600">{t.zone}</p></div><span className="text-[11px] text-slate-400">{t.type}</span><span className="text-[11px] text-slate-300">{t.people}</span><span className={`text-[10px] font-bold ${t.status==="DEPLOYED"?"text-success":t.status==="EN ROUTE"?"text-cyan":"text-amber"}`}>{t.status}</span><span className="text-[11px] text-slate-400">{t.eta}</span><button onClick={() => setActiveNav("Teams")} className="text-slate-500 hover:text-white"><ChevronRight size={15}/></button></div>)}</section><section className="panel p-4"><PanelTitle eyebrow="Team readiness" title="Deployment capacity"/><div className="mt-4 space-y-4"><MiniStat label="Available teams" value={String(readiness.available)}/><MiniStat label="Deployed" value={String(readiness.deployed)}/><MiniStat label="Standby" value={String(readiness.standby)}/><MiniStat label="Comms health" value={`${commsHealth}%`}/><div className="rounded-xl border border-line bg-slate-950/30 p-3"><p className="text-[10px] font-semibold">Operational note</p><p className="mt-2 text-[11px] leading-5 text-slate-500">Team 04 has flood rescue capability and is within the recommended pre-positioning zone.</p></div></div></section></div></>;
}

function PredictionPage({ notify, refreshAll }: any) {
  const { forecastSeries, evidenceRows, predictionSummary, topIncident } = useConsoleData();
  const { riskBand, confidence, impactWindow, population, trend } = predictionSummary;
  const [explain, setExplain] = useState<ExplainState | null>(null);

  // The decision trail is the backend's XAI explanation for the top incident.
  const openDecisionTrail = async () => {
    if (!topIncident?.incident_id) {
      notify("Model decision trail opened");
      return;
    }
    try {
      const result = await api.explain(topIncident.incident_id);
      setExplain({
        priority: result.priority_band,
        score: result.priority_score,
        text: result.explanation || result.xai_raw || "No rationale recorded for this incident.",
      });
    } catch {
      setExplain({ priority: "UNAVAILABLE", score: 0, text: "The prediction service did not respond." });
    }
    notify("Model decision trail opened");
  };

  return <><PageHeader eyebrow="AI systems / Prediction Engine" title="Prediction engine" description="Forecast hazards, estimate impact windows, and expose evidence and confidence behind each prediction."><span className="chip"><BrainCircuit size={12} className="text-cyan"/> Models healthy</span><button onClick={()=>{refreshAll(); notify("Prediction models refreshed");}} className="icon-btn"><RefreshCw size={16}/></button></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_340px]"><section className="panel p-4"><div className="flex items-center justify-between"><div><p className="eyebrow">Current forecast</p><h2 className="mt-1 text-lg font-bold">Flash flood propagation</h2></div><span className="chip !border-danger/20 !text-danger">{riskBand}</span></div><div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4"><MiniStat label="Confidence" value={confidence}/><MiniStat label="Impact window" value={impactWindow}/><MiniStat label="Population" value={population}/><MiniStat label="Trend" value={trend}/></div><div className="mt-5 rounded-xl border border-line bg-slate-950/30 p-4"><p className="text-[10px] font-semibold text-slate-300">Forecast timeline</p><div className="mt-5 flex items-end gap-2">{forecastSeries.map((v,i)=><div key={i} className="flex-1"><div className="rounded-t bg-danger/60" style={{height:`${v*1.6}px`}}/><p className="mt-2 text-center text-[9px] text-slate-600">T+{i*10}m</p></div>)}</div></div></section><section className="panel p-4"><PanelTitle eyebrow="Evidence" title="Why the model believes this"/><div className="mt-3 space-y-2">{evidenceRows.map((row,i)=><div key={row.label} className="rounded-lg border border-line p-3"><div className="flex items-center gap-2"><CheckCircle2 size={13} className="text-success"/><span className="text-xs font-semibold">{row.label}</span><span className="ml-auto text-[10px] text-slate-500">{row.confidence}</span></div></div>)}</div><button onClick={openDecisionTrail} className="mt-4 w-full rounded-lg border border-line py-2.5 text-[11px] font-semibold">View model decision trail</button>{explain && <div className="mt-3 rounded-xl border border-cyan/20 bg-cyan/[.04] p-3"><p className="text-[10px] font-semibold text-cyan">Decision trail · {explain.priority} ({Math.round(explain.score)})</p><p className="mt-2 text-[11px] leading-5 text-slate-400">{explain.text}</p></div>}</section></div></>;
}

interface ExplainState { priority: string; score: number; text: string }

function CommanderPage({ notify }: any) {
  const { allocationPlan, constraints, pendingActions, refreshAll } = useConsoleData();
  const [busy, setBusy] = useState(false);

  /**
   * "Review" now performs the actual commander decision on the pending action
   * behind the recommendation, then re-reads the approval queue. The toast text
   * is unchanged.
   */
  const review = async (index: number) => {
    const action = pendingActions[index];
    if (!action || busy) return;
    setBusy(true);
    try {
      await api.updateAction(action.action_id, "approved");
      refreshAll();
      notify(`Recommendation ${index + 1} approved for dispatch review`);
    } catch {
      notify(`Recommendation ${index + 1} could not be approved`);
    } finally {
      setBusy(false);
    }
  };

  return <><PageHeader eyebrow="AI systems / Resource Commander" title="Resource Commander" description="Translate incident needs into concrete, reviewable resource allocations."><span className="chip"><Crosshair size={12} className="text-cyan"/> Decision support</span></PageHeader><div className="grid gap-4 lg:grid-cols-2"><section className="panel p-4"><PanelTitle eyebrow="Recommended" title="Allocation plan"/><div className="mt-3 space-y-2">{allocationPlan.map((x,i)=><div key={`${x}-${i}`} className="rounded-xl border border-line bg-slate-950/30 p-3"><div className="flex items-start gap-3"><div className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-md bg-cyan/10 text-[10px] font-bold text-cyan">{i+1}</div><div className="flex-1"><p className="text-xs font-semibold">{x}</p><p className="mt-1 text-[10px] text-slate-500">Expected impact reduction · {92-i*4}% confidence</p></div><button disabled={busy} onClick={()=>review(i)} className="rounded-lg bg-cyan px-2.5 py-1.5 text-[10px] font-bold text-[#04101b] disabled:opacity-50">Review</button></div></div>)}</div></section><section className="panel p-4"><PanelTitle eyebrow="Constraint monitor" title="What could block the plan"/><div className="mt-3 space-y-3">{constraints.map(c=><Constraint key={c.title} title={c.title} value={c.value} status={c.status}/>)}</div><div className="mt-4 rounded-xl border border-amber/20 bg-amber/[.04] p-3"><p className="text-[10px] font-semibold text-amber">Operator attention</p><p className="mt-2 text-[11px] leading-5 text-slate-400">Water and fuel reserves may constrain response if the incident expands beyond the current forecast.</p></div></section></div></>;
}

function AssistantPage({ role, notify }: { role: Role; notify: (s:string)=>void }) {
  const { zoneId, feedHealth, topIncident } = useConsoleData();
  // Real command-center conversation: POST /api/command/query with a stable
  // conversation id. The optimistic user turn and the toast are unchanged.
  const assistant = useAssistant(INITIAL_ASSISTANT_MESSAGES, zoneId, notify);
  const { messages, input, setInput, send } = assistant;
  const contextLabel = topIncident?.incident_id ?? "No active incident";
  return <><PageHeader eyebrow="AI systems / Assistant" title="Ask AegisAI" description="Conversational access to the live operational picture, with traceable recommendations and explicit operator confirmation."><span className="chip"><Radio size={12} className={assistant.lastReplyFromAi ? "text-success" : "text-slate-500"}/> Live context · {role} mode</span></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]"><section className="panel flex min-h-[620px] flex-col"><div className="border-b border-line px-4 py-3"><p className="text-xs font-semibold">Operational conversation</p><p className="mt-1 text-[10px] text-slate-500">Context: {contextLabel} · Ahmedabad · {feedHealth.sourceCount} connected sources</p></div><div className="flex-1 space-y-4 overflow-auto p-4">{messages.map((m,i)=><div key={i} className={`flex ${m.who==="user"?"justify-end":""}`}><div className={`max-w-[75%] rounded-2xl px-4 py-3 text-xs leading-5 ${m.who==="user"?"bg-cyan text-[#04101b]":"border border-line bg-slate-950/40 text-slate-300"}`}>{m.text}</div></div>)}{assistant.isThinking && <div className="flex"><div className="rounded-2xl border border-line bg-slate-950/40 px-4 py-3 text-xs text-slate-500">Correlating live context…</div></div>}</div><div className="border-t border-line p-3"><div className="flex gap-2"><input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&send()} placeholder="Ask about incidents, routes, resources..." className="h-11 min-w-0 flex-1 rounded-xl border border-line bg-slate-950/50 px-3 text-xs outline-none focus:border-cyan/40"/><button onClick={send} className="flex h-11 w-11 items-center justify-center rounded-xl bg-cyan text-[#04101b]"><Send size={16}/></button></div></div></section><section className="space-y-4"><div className="panel p-4"><PanelTitle eyebrow="Suggested prompts" title="Quick actions"/><div className="mt-3 space-y-2">{["Summarize the current situation","Which team should move next?","Show blocked routes","What resources are low?","Explain the flood prediction"].map(x=><button key={x} onClick={()=>setInput(x)} className="w-full rounded-lg border border-line px-3 py-2.5 text-left text-[11px] text-slate-300 hover:bg-slate-900">{x}</button>)}</div></div><div className="panel p-4"><PanelTitle eyebrow="Trust layer" title="Every answer should show"/><div className="mt-3 space-y-3 text-[11px] text-slate-400"><div className="flex gap-2"><CheckCircle2 size={14} className="text-success"/> Evidence sources</div><div className="flex gap-2"><CheckCircle2 size={14} className="text-success"/> Confidence / uncertainty</div><div className="flex gap-2"><CheckCircle2 size={14} className="text-success"/> Recommended action</div><div className="flex gap-2"><CheckCircle2 size={14} className="text-success"/> Human confirmation required</div></div></div></section></div></>;
}

function PanelTitle({ eyebrow, title }: { eyebrow:string; title:string }) { return <div><p className="eyebrow">{eyebrow}</p><h2 className="mt-1 text-sm font-semibold">{title}</h2></div>; }
function MiniStat({ label, value }: { label:string; value:string }) { return <div className="rounded-lg border border-line bg-slate-950/30 p-3"><p className="text-[9px] uppercase tracking-wider text-slate-600">{label}</p><p className="mt-1 text-sm font-bold text-slate-200">{value}</p></div>; }
function Pressure({ label, value, note }: any) { return <div><div className="flex items-center justify-between text-[11px]"><span>{label}</span><span className="text-slate-500">{value}</span></div><div className="mt-1.5 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{width:value}}/></div><p className="mt-1 text-[9px] text-slate-600">{note}</p></div>; }
function SelectLike({ label, value }: any) { return <div><p className="mb-1 text-[10px] text-slate-600">{label}</p><div className="flex items-center justify-between rounded-lg border border-line bg-slate-950/40 px-3 py-2.5 text-[11px] text-slate-300">{value}<ChevronRight size={13} className="rotate-90 text-slate-600"/></div></div>; }
function Constraint({ title, value, status }: any) { return <div className="rounded-xl border border-line bg-slate-950/30 p-3"><div className="flex items-center justify-between"><span className="text-xs">{title}</span><span className="text-[10px] text-slate-500">{status}</span></div><div className="mt-2 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{width:value}}/></div><p className="mt-1 text-right text-[9px] text-slate-600">{value}</p></div>; }

export default App;
