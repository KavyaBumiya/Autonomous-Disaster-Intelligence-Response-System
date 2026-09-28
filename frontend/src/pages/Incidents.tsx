import { useEffect, useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import { PageHeader, MiniStat } from "../components/ui";

const { Search, RefreshCw, X, ChevronRight, ClipboardCheck } = Icons;

export function Incidents({ alerts, selected, setSelected, query, setQuery, notify, refreshAll }: any) {
  const data = useConsoleData();
  const incident = data.selectedIncidentFor(selected);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [workflowBusy, setWorkflowBusy] = useState(false);

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

  const createResponseWorkflow = async () => {
    if (!incident || workflowBusy) return;
    setWorkflowBusy(true);
    try {
      const result = await api.decisionRecommend({
        incident_id: incident.incident_id,
        action_type: "rescue",
        hazard_type: incident.disaster_type,
        location: { lat: incident.lat, lng: incident.lng },
        context: {
          operator_instruction: "Create a response workflow for this live incident. Break it into immediate safety, rescue, resource, route, and monitoring steps. Do not execute anything; return a reviewable plan.",
          incident_status: incident.status,
          priority_score: incident.priority_score,
          victim_count: incident.victim_count,
          report_count: incident.report_count,
        },
      });
      refreshAll();
      notify(`Response workflow drafted · ${Math.round(result.confidence * 100)}% confidence · pending approval`);
    } catch {
      notify("AegisAI could not create the response workflow");
    } finally {
      setWorkflowBusy(false);
    }
  };

  return <><PageHeader eyebrow="Operations / Incidents" title="Incident command queue" description="Verify, prioritize and assign response actions across incoming disaster signals."><div className="relative"><Search size={14} className="absolute left-3 top-2.5 text-slate-500"/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search incidents..." className="h-9 w-52 rounded-lg border border-line bg-slate-950/50 pl-9 pr-3 text-xs outline-none"/></div><button onClick={()=>{refreshAll(); notify("Incident feed refreshed");}} className="icon-btn"><RefreshCw size={16}/></button></PageHeader><div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]"><section className="panel overflow-hidden"><div className="grid grid-cols-[1.1fr_1fr_.7fr_.7fr_24px] border-b border-line px-4 py-3 text-[10px] uppercase tracking-wider text-slate-600"><span>Incident</span><span>Location</span><span>Confidence</span><span>Status</span><span/></div>{alerts.map((a:any)=><button key={a.id} onClick={()=>setSelected(a)} className={`grid w-full grid-cols-[1.1fr_1fr_.7fr_.7fr_24px] items-center border-b border-line/70 px-4 py-4 text-left hover:bg-slate-900/50 ${selected?.id===a.id?"bg-cyan/[.035]":""}`}><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${a.level==="CRITICAL"?"bg-danger":a.level==="HIGH"?"bg-amber":"bg-cyan"}`}/><div><p className="text-xs font-semibold text-white">{a.title}</p><p className="text-[9px] text-slate-600">{a.id} · {a.time}</p></div></div><span className="text-[11px] text-slate-400">{a.place}</span><span className="text-[11px] font-semibold text-slate-300">{a.confidence}%</span><span className={`text-[10px] font-semibold ${a.status==="Active"?"text-danger":a.status==="Verified"?"text-success":"text-amber"}`}>{a.status}</span><ChevronRight size={14} className="text-slate-600"/></button>)}</section><section className="panel p-4"><p className="eyebrow">Incident detail</p><h2 className="mt-1 text-base font-bold">{selected?.title ?? "No incident selected"}</h2><p className="mt-1 text-xs text-slate-500">{selected?.place ?? "Select an incident to view details"}</p><div className="mt-4 grid grid-cols-2 gap-2"><MiniStat label="Confidence" value={`${selected?.confidence ?? 0}%`}/><MiniStat label="Priority" value={selected?.level ?? "—"}/><MiniStat label="Evidence" value={incident ? `${Math.max(1, Math.round(incident.report_count))} streams` : "—"}/><MiniStat label="Last update" value={selected?.time ?? "—"}/></div><div className="mt-4 rounded-xl border border-line bg-slate-950/30 p-3"><p className="text-[10px] font-semibold text-slate-300">AI assessment</p><p className="mt-2 text-[11px] leading-5 text-slate-400">{assessment}</p></div><button disabled={!incident || workflowBusy} onClick={createResponseWorkflow} className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-danger py-2.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"><ClipboardCheck size={14}/> {workflowBusy ? "Creating AI workflow…" : "Create response workflow"}</button></section></div></>;
}
