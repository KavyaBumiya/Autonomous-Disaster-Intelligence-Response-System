import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import { PageHeader, PanelTitle, Pressure } from "../components/ui";

const { Package, CheckCircle2, X } = Icons;

export function Resources({ notify }: any) {
  const { resourceCards, allocationQueue, pressure, topIncident, refreshAll } = useConsoleData();
  const [assigning, setAssigning] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", resource_type: "team", capacity: "1", lat: "", lng: "" });

  const approveAllocation = async () => {
    if (!topIncident || assigning) return;
    setAssigning(true);
    try {
      await api.assignResources(topIncident.incident_id);
      refreshAll();
      notify("AI resource allocation drafted and added to approval queue");
    } catch {
      notify("Allocation could not be drafted — backend unavailable");
    } finally {
      setAssigning(false);
    }
  };

  const addResource = async () => {
    if (!form.name.trim()) return notify("Enter a resource name");
    try {
      await api.registerResource({
        name: form.name.trim(),
        resource_type: form.resource_type as "team" | "vehicle" | "supply" | "shelter",
        capacity: Math.max(1, Number(form.capacity) || 1),
        lat: form.lat.trim() ? Number(form.lat) : null,
        lng: form.lng.trim() ? Number(form.lng) : null,
      });
      setAddOpen(false);
      setForm({ name: "", resource_type: "team", capacity: "1", lat: "", lng: "" });
      refreshAll();
      notify("Resource added to the operational pool");
    } catch {
      notify("Resource could not be added");
    }
  };

  return <><PageHeader eyebrow="Operations / Resources" title="Resource command" description="Track available capacity and allocate people, vehicles and relief supplies to active incidents."><button onClick={() => setAddOpen(true)} className="flex items-center gap-2 rounded-lg bg-cyan px-3 py-2 text-[11px] font-bold text-[#04101b]"><Package size={14}/> Add resource</button></PageHeader><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{resourceCards.map((r:any)=><div key={r.label} className="panel p-4"><div className="flex items-center justify-between"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan/10 text-cyan"><r.icon size={17}/></div><span className="chip">{r.total > 0 ? Math.round(r.value/r.total*100) : 0}%</span></div><p className="mt-4 text-xs text-slate-500">{r.label}</p><p className="mt-1 text-2xl font-bold">{r.value.toLocaleString()}</p><p className="text-[10px] text-slate-600">of {r.total.toLocaleString()} available</p><div className="mt-3 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{width:`${r.total > 0 ? Math.round(r.value/r.total*100) : 0}%`}}/></div></div>)}</div><div className="mt-4 grid gap-4 lg:grid-cols-2"><section className="panel"><PanelTitle eyebrow="Allocation queue" title="Recommended allocations"/><div className="divide-y divide-line/70">{allocationQueue.map((x,i)=><div key={`${x}-${i}`} className="flex items-center gap-3 px-4 py-4"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan/10 text-cyan">{i+1}</div><p className="flex-1 text-xs text-slate-300">{x}</p><span className="chip">AI recommended</span><button disabled={assigning} onClick={approveAllocation} className="icon-btn disabled:opacity-50"><CheckCircle2 size={15}/></button></div>)}{allocationQueue.length===0 && <div className="p-4 text-[11px] text-slate-500">No pending AI allocations for the current incident.</div>}</div></section><section className="panel"><PanelTitle eyebrow="Stock health" title="Supply pressure"/><div className="space-y-4 p-4">{pressure.map(p=><Pressure key={p.label} label={p.label} value={p.value} note={p.note}/>)}</div></section></div>
    {addOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"><div className="w-full max-w-lg rounded-2xl border border-line bg-[#0a1726] p-5 shadow-2xl"><div className="flex items-center justify-between"><div><p className="eyebrow">Resource pool</p><h2 className="mt-1 text-base font-bold">Add new resource</h2></div><button onClick={()=>setAddOpen(false)} className="icon-btn"><X size={15}/></button></div><div className="mt-4 grid gap-3 sm:grid-cols-2"><label className="text-[11px] text-slate-400 sm:col-span-2">Name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})} className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none" placeholder="Team Alpha / Ambulance 04"/></label><label className="text-[11px] text-slate-400">Type<select value={form.resource_type} onChange={e=>setForm({...form,resource_type:e.target.value})} className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none"><option value="team">Team</option><option value="vehicle">Vehicle</option><option value="supply">Supply</option><option value="shelter">Shelter</option></select></label><label className="text-[11px] text-slate-400">Capacity<input type="number" min="1" value={form.capacity} onChange={e=>setForm({...form,capacity:e.target.value})} className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none"/></label><label className="text-[11px] text-slate-400">Latitude<input value={form.lat} onChange={e=>setForm({...form,lat:e.target.value})} className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none" placeholder="22.3072"/></label><label className="text-[11px] text-slate-400">Longitude<input value={form.lng} onChange={e=>setForm({...form,lng:e.target.value})} className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none" placeholder="73.1812"/></label></div><div className="mt-5 flex justify-end gap-2"><button onClick={()=>setAddOpen(false)} className="rounded-lg border border-line px-4 py-2 text-[11px] font-semibold text-slate-300">Cancel</button><button onClick={addResource} className="rounded-lg bg-cyan px-4 py-2 text-[11px] font-bold text-[#04101b]">Add resource</button></div></div></div>}
  </>;
}
