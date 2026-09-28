import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import { PageHeader, PanelTitle, MiniStat } from "../components/ui";

const { BrainCircuit, RefreshCw, CheckCircle2 } = Icons;

interface ExplainState {
  priority: string;
  score: number;
  text: string;
}

export function PredictionPage({ notify, refreshAll }: any) {
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
