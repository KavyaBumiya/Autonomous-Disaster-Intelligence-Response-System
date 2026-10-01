import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { api } from "../lib/api";
import { PageHeader, PanelTitle, Constraint } from "../components/ui";

const { Crosshair, CheckCircle2, X } = Icons;

export function CommanderPage({ notify }: any) {
  const { allocationPlan, constraints, pendingActions, refreshAll } = useConsoleData();
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  /**
   * Approve or reject a specific pending action by id.
   *
   * Rows are derived from `pendingActions` itself rather than matched against
   * `allocationPlan` by index, so the button can never approve a different
   * action than the one displayed — which on an approval gate would be a
   * correctness bug, not a cosmetic one.
   */
  const decide = async (actionId: string, approve: boolean) => {
    if (busy) return;
    if (!approve && !reason.trim()) return notify("Give a reason before rejecting");
    setBusy(true);
    try {
      if (approve) {
        await api.decisionApprove(actionId, "Approved by command center");
      } else {
        await api.decisionReject(actionId, reason.trim());
      }
      setRejecting(null);
      setReason("");
      refreshAll();
      notify(approve ? "Action approved and released to dispatch" : "Action rejected");
    } catch {
      notify(approve ? "Action could not be approved" : "Action could not be rejected");
    } finally {
      setBusy(false);
    }
  };

  const rows = pendingActions.slice(0, 4);
  const empty = rows.length === 0;

  return (
    <>
      <PageHeader
        eyebrow="AI systems / Resource Commander"
        title="Resource Commander"
        description="Translate incident needs into concrete, reviewable resource allocations."
      >
        <span className="chip">
          <Crosshair size={12} className="text-cyan" /> Decision support
        </span>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <PanelTitle eyebrow="Recommended" title="Allocation plan" />
          {empty ? (
            <p className="mt-4 rounded-xl border border-line bg-slate-950/30 p-3 text-[11px] leading-5 text-slate-500">
              No actions are awaiting approval. The resource commander raises an allocation when an
              incident needs capacity; until then there is nothing to review.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              {rows.map((action: any, i: number) => (
                <div key={action.action_id} className="rounded-xl border border-line bg-slate-950/30 p-3">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-md bg-cyan/10 text-[10px] font-bold text-cyan">
                      {i + 1}
                    </div>
                    <div className="flex-1">
                      <p className="text-xs font-semibold">
                        {action.description ||
                          `${action.action_type} for this incident`}
                      </p>
                      {/* Real figure from the decision engine, not a decorative one. */}
                      <p className="mt-1 text-[10px] text-slate-500">
                        {typeof action.priority_score === "number"
                          ? `Priority ${Math.round(action.priority_score)}/100`
                          : "Priority not scored"}
                        {action.status ? ` · ${action.status}` : ""}
                      </p>

                      {rejecting === action.action_id && (
                        <div className="mt-2 flex gap-2">
                          <input
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="Reason for rejection"
                            className="h-8 flex-1 rounded-lg border border-line bg-slate-950/60 px-2.5 text-[11px] text-white outline-none"
                          />
                          <button
                            disabled={busy}
                            onClick={() => decide(action.action_id, false)}
                            className="rounded-lg bg-danger px-2.5 text-[10px] font-bold text-white disabled:opacity-50"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => {
                              setRejecting(null);
                              setReason("");
                            }}
                            className="rounded-lg border border-line px-2 text-[10px] text-slate-400"
                          >
                            <X size={11} />
                          </button>
                        </div>
                      )}
                    </div>

                    <div className="flex shrink-0 gap-1.5">
                      <button
                        disabled={busy}
                        onClick={() => decide(action.action_id, true)}
                        className="flex items-center gap-1.5 rounded-lg bg-cyan px-2.5 py-1.5 text-[10px] font-bold text-[#04101b] disabled:opacity-50"
                      >
                        <CheckCircle2 size={12} /> Review
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => {
                          setRejecting(rejecting === action.action_id ? null : action.action_id);
                          setReason("");
                        }}
                        title="Reject with a reason"
                        className="rounded-lg border border-line px-2 py-1.5 text-[10px] text-slate-400 hover:text-danger disabled:opacity-50"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-[9px] leading-4 text-slate-600">
            Approval is the human gate: the AI can only ever raise an action, never authorise a dispatch.
          </p>
        </section>

        <section className="panel p-4">
          <PanelTitle eyebrow="Constraint monitor" title="What could block the plan" />
          <div className="mt-3 space-y-3">
            {constraints.map((c) => (
              <Constraint key={c.title} title={c.title} value={c.value} status={c.status} />
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-amber/20 bg-amber/[.04] p-3">
            <p className="text-[10px] font-semibold text-amber">Operator attention</p>
            <p className="mt-2 text-[11px] leading-5 text-slate-400">
              Water and fuel reserves may constrain response if the incident expands beyond the current
              forecast. The monitor above reads live resource counts, not projections.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
