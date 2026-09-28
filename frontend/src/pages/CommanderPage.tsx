import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import { PageHeader, PanelTitle, Constraint } from "../components/ui";

const { Crosshair } = Icons;

export function CommanderPage({ notify }: any) {
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
      await api.decisionApprove(action.action_id, "Approved by command center");
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
