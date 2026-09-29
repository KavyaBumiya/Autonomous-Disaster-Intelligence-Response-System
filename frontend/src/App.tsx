import { useMemo, useState } from "react";
import * as Icons from "lucide-react";
import {
  ConsoleDataProvider,
  useConsoleData,
  type ConsoleVisuals,
  type ResourceSlotVisual,
} from "./lib/consoleData";
import {
  Overview,
  LiveMap,
  Incidents,
  Resources,
  RoutesPage,
  TeamsPage,
  PredictionPage,
  CommanderPage,
  AssistantPage,
  FloodSimulation,
  type Role,
} from "./pages";

const {
  Activity, Bell, Bot, Crosshair, Gauge, HeartPulse, MapPin, Menu,
  MessageSquare, Navigation, Package, Radio, Shield, Siren, Truck, Users, Waves, X,
} = Icons;

export type NavItem =
  | "Overview"
  | "Live Map"
  | "Incidents"
  | "Resources"
  | "Routes"
  | "Teams"
  | "Prediction Engine"
  | "Resource Commander"
  | "AI Assistant"
  | "Flood Simulation";

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
    "Citizen reports",
    "Weather nowcast",
  ],
  constraintTitles: ["Ambulance availability", "Rescue team coverage", "Water reserve", "Fuel stock"],
  pressureLabels: ["Water", "Medical kits", "Food", "Fuel"],
};

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
    { label: "Flood Simulation", icon: Waves, section: "Simulation" },
  ];

  const filteredAlerts = useMemo(
    () => alerts.filter((a) => `${a.title} ${a.place}`.toLowerCase().includes(query.toLowerCase())),
    [alerts, query],
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
          <span className="chip"><Radio size={12} className={data.feedHealth.isStreamNominal ? "text-success" : data.feedHealth.isNominal ? "text-amber" : "text-danger"}/> {data.feedHealth.statusLabel}</span>
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
          <div className="mb-5 px-2 pt-2"><p className="eyebrow">Operations</p><p className="mt-1 text-xs text-slate-500">{data.zoneName}</p></div>
          <nav className="space-y-1">
            {nav.map((item) => {
              const Icon = item.icon;
              return <div key={item.label}>
                {item.section && <p className="mb-2 mt-5 px-2 text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500">{item.section}</p>}
                <button onClick={() => openNav(item.label)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs transition ${activeNav === item.label ? "bg-cyan/10 text-cyan ring-1 ring-cyan/15" : "text-slate-400 hover:bg-slate-900/60 hover:text-white"}`}>
                  <Icon size={16}/><span className="flex-1">{item.label}</span>{item.count ? <span className="rounded-md bg-danger/10 px-1.5 py-0.5 text-[9px] font-bold text-danger">{item.count}</span> : null}
                </button>
              </div>;
            })}
          </nav>
          <div className="absolute bottom-4 left-3 right-3 rounded-xl border border-line bg-slate-950/40 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold"><div className={`h-2 w-2 rounded-full ${data.feedHealth.isNominal ? "bg-success" : "bg-danger"}`}/><span>{data.feedHealth.systemLabel}</span></div>
            <p className="mt-1 text-[10px] text-slate-500">Last sync {data.freshness} ago · {data.feedHealth.sourceCount} sources</p>
          </div>
        </aside>

        <main className="min-w-0 flex-1 p-4 lg:p-6">
          <div className="mx-auto max-w-[1600px]">
            {activeNav === "Overview" && <Overview setActiveNav={openNav} alertOpen={alertOpen} setAlertOpen={setAlertOpen} selectedAlert={selectedAlert} setSelectedAlert={setSelectedAlert} mapLayer={mapLayer} setMapLayer={setMapLayer} filteredAlerts={filteredAlerts} query={query} setQuery={setQuery} notify={notify} refreshAll={refreshAll} filtersOpen={filtersOpen} setFiltersOpen={setFiltersOpen} />}
            {activeNav === "Live Map" && <LiveMap mapLayer={mapLayer} setMapLayer={setMapLayer} notify={notify}/>}
            {activeNav === "Incidents" && <Incidents alerts={filteredAlerts} selected={selectedAlert} setSelected={setSelectedAlert} query={query} setQuery={setQuery} notify={notify} refreshAll={refreshAll}/>}
            {activeNav === "Resources" && <Resources notify={notify}/>}
            {activeNav === "Routes" && <RoutesPage notify={notify} refreshAll={refreshAll} setActiveNav={openNav}/>}
            {activeNav === "Teams" && <TeamsPage notify={notify} setActiveNav={openNav}/>}
            {activeNav === "Prediction Engine" && <PredictionPage notify={notify} refreshAll={refreshAll}/>}
            {activeNav === "Resource Commander" && <CommanderPage notify={notify}/>}
            {activeNav === "AI Assistant" && <AssistantPage role={role} notify={notify}/>}
            {activeNav === "Flood Simulation" && <FloodSimulation />}
          </div>
        </main>
      </div>

      {toast && <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-line bg-[#0b1828] px-4 py-2.5 text-xs font-semibold text-slate-200 shadow-2xl">{toast}</div>}
    </div>
  );
}

export default App;
