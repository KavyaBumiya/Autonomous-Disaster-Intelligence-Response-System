import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import { PageHeader, PanelTitle, MiniStat } from "../components/ui";

const { Send, X, ChevronRight } = Icons;

export function TeamsPage({ notify, setActiveNav }: any) {
  const { teamRows, readiness, feedHealth, resources, topIncident, refreshAll } = useConsoleData();
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [teamId, setTeamId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const commsHealth = feedHealth.sourceCount > 0
    ? Math.round((feedHealth.healthyFeeds / feedHealth.sourceCount) * 100)
    : 0;
  const freeTeams = (resources ?? []).filter(
    (resource) => resource.resource_type === "team" && resource.available && resource.current_load <= 0 && !resource.assigned_zone_id,
  );

  const openDispatch = () => {
    if (freeTeams.length === 0) return notify("No free or standby team is available");
    setTeamId(freeTeams[0].resource_id);
    setInstruction("");
    setDispatchOpen(true);
  };

  const dispatchTeam = async () => {
    const team = freeTeams.find((item) => item.resource_id === teamId);
    if (!team || !topIncident || !instruction.trim() || busy) {
      if (!topIncident) notify("Select an active incident before creating a dispatch");
      else if (!instruction.trim()) notify("Add dispatch instructions");
      return;
    }
    setBusy(true);
    try {
      const result = await api.decisionRecommend({
        incident_id: topIncident.incident_id,
        action_type: "dispatch",
        hazard_type: topIncident.disaster_type,
        location: { lat: topIncident.lat, lng: topIncident.lng },
        context: {
          resource_id: team.resource_id,
          resource_name: team.name,
          operator_instruction: instruction.trim(),
          dispatch_only_if_available: true,
          current_load: team.current_load,
          available: team.available,
        },
      });
      setDispatchOpen(false);
      refreshAll();
      notify(`Dispatch instruction drafted for ${team.name} · pending approval`);
      if (!result.requires_human_approval) notify("Backend returned a dispatch without an approval flag");
    } catch {
      notify("AegisAI could not create the dispatch instruction");
    } finally {
      setBusy(false);
    }
  };

  return <><PageHeader eyebrow="Operations / Teams" title="Field teams" description="See who is deployed, where they are, what they can do, and how quickly they can respond."><button onClick={openDispatch} className="flex items-center gap-2 rounded-lg bg-cyan px-3 py-2 text-[11px] font-bold text-[#04101b]"><Send size={13}/> Dispatch team</button></PageHeader><div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]"><section className="panel overflow-hidden"><div className="grid grid-cols-[1.3fr_1fr_.7fr_.8fr_.6fr_24px] border-b border-line px-4 py-3 text-[10px] uppercase tracking-wider text-slate-600"><span>Team</span><span>Specialty</span><span>People</span><span>Status</span><span>ETA</span><span/></div>{teamRows.map(t=><div key={t.name} className="grid grid-cols-[1.3fr_1fr_.7fr_.8fr_.6fr_24px] items-center border-b border-line/70 px-4 py-4"><div><p className="text-xs font-semibold">{t.name}</p><p className="mt-1 text-[10px] text-slate-600">{t.zone}</p></div><span className="text-[11px] text-slate-400">{t.type}</span><span className="text-[11px] text-slate-300">{t.people}</span><span className={`text-[10px] font-bold ${t.status==="DEPLOYED"?"text-success":t.status==="EN ROUTE"?"text-cyan":"text-amber"}`}>{t.status}</span><span className="text-[11px] text-slate-400">{t.eta}</span><button onClick={() => setActiveNav("Teams")} className="text-slate-500 hover:text-white"><ChevronRight size={15}/></button></div>)}</section><section className="panel p-4"><PanelTitle eyebrow="Team readiness" title="Deployment capacity"/><div className="mt-4 space-y-4"><MiniStat label="Available teams" value={String(readiness.available)}/><MiniStat label="Deployed" value={String(readiness.deployed)}/><MiniStat label="Standby" value={String(readiness.standby)}/><MiniStat label="Comms health" value={`${commsHealth}%`}/><div className="rounded-xl border border-line bg-slate-950/30 p-3"><p className="text-[10px] font-semibold">Dispatch eligibility</p><p className="mt-2 text-[11px] leading-5 text-slate-500">Only teams marked available, with zero current load and no assigned zone, are offered for new dispatch instructions.</p></div></div></section></div>
    {dispatchOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"><div className="w-full max-w-lg rounded-2xl border border-line bg-[#0a1726] p-5 shadow-2xl"><div className="flex items-center justify-between"><div><p className="eyebrow">Team dispatch</p><h2 className="mt-1 text-base font-bold">Create dispatch instruction</h2></div><button onClick={()=>setDispatchOpen(false)} className="icon-btn"><X size={15}/></button></div><div className="mt-4 space-y-3"><label className="block text-[11px] text-slate-400">Available / standby team<select value={teamId} onChange={e=>setTeamId(e.target.value)} className="mt-1 h-10 w-full rounded-lg border border-line bg-slate-950/50 px-3 text-xs text-white outline-none">{freeTeams.map(team=><option key={team.resource_id} value={team.resource_id}>{team.name} · capacity {team.capacity}</option>)}</select></label><label className="block text-[11px] text-slate-400">Dispatch instruction<textarea value={instruction} onChange={e=>setInstruction(e.target.value)} className="mt-1 min-h-28 w-full rounded-lg border border-line bg-slate-950/50 p-3 text-xs text-white outline-none" placeholder="Deploy to the affected zone, establish a rescue point, report status every 15 minutes…"/></label><div className="rounded-xl border border-amber/20 bg-amber/[.04] p-3 text-[10px] leading-5 text-slate-400">This sends the instruction to the AegisAI decision engine. It creates a <b className="text-amber">pending approval</b> dispatch action; it does not deploy the team automatically.</div></div><div className="mt-5 flex justify-end gap-2"><button onClick={()=>setDispatchOpen(false)} className="rounded-lg border border-line px-4 py-2 text-[11px] font-semibold text-slate-300">Cancel</button><button disabled={busy || !topIncident} onClick={dispatchTeam} className="rounded-lg bg-cyan px-4 py-2 text-[11px] font-bold text-[#04101b] disabled:opacity-50">{busy ? "Sending to AI…" : "Create dispatch"}</button></div></div></div>}
  </>;
}