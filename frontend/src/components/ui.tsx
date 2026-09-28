import * as Icons from "lucide-react";

const { ChevronRight } = Icons;

export function PageHeader({ eyebrow, title, description, action, children }: any) {
  return <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
    <div><p className="eyebrow">{eyebrow}</p><h1 className="mt-1 text-xl font-bold tracking-tight text-white md:text-2xl">{title}</h1>{description && <p className="mt-1 max-w-2xl text-xs text-slate-500">{description}</p>}</div>
    <div className="flex items-center gap-2">{children}{action}</div>
  </div>;
}

export function Metric({ icon: Icon, label, value, sub, tone }: { icon: any; label: string; value: string; sub: string; tone: "danger"|"cyan"|"amber"|"success" }) {
  const tones = { danger: "text-danger bg-danger/10", cyan: "text-cyan bg-cyan/10", amber: "text-amber bg-amber/10", success: "text-success bg-success/10" };
  return <div className="panel p-4"><div className="flex items-center gap-3"><div className={`flex h-9 w-9 items-center justify-center rounded-lg ${tones[tone]}`}><Icon size={17}/></div><div className="min-w-0"><p className="eyebrow">{label}</p><p className="mt-0.5 text-xl font-bold tracking-tight">{value}</p></div></div><p className="mt-3 text-[10px] text-slate-500">{sub}</p></div>;
}

export function Recommendation({ n, text, confidence, onClick }: any) {
  return <button onClick={onClick} className="w-full rounded-xl border border-line bg-slate-950/30 p-3 text-left transition hover:border-cyan/20 hover:bg-cyan/[.025]"><div className="flex gap-3"><span className="font-mono text-[10px] text-cyan/70">{n}</span><div className="flex-1"><p className="text-[11px] leading-4 text-slate-200">{text}</p><p className="mt-1.5 text-[9px] text-slate-500">Confidence {confidence} · explainable</p></div><ChevronRight size={13} className="mt-0.5 text-slate-600"/></div></button>;
}

export function PanelTitle({ eyebrow, title }: { eyebrow:string; title:string }) {
  return <div><p className="eyebrow">{eyebrow}</p><h2 className="mt-1 text-sm font-semibold">{title}</h2></div>;
}
export function MiniStat({ label, value }: { label:string; value:string }) {
  return <div className="rounded-lg border border-line bg-slate-950/30 p-3"><p className="text-[9px] uppercase tracking-wider text-slate-600">{label}</p><p className="mt-1 text-sm font-bold text-slate-200">{value}</p></div>;
}
export function Pressure({ label, value, note }: any) {
  return <div><div className="flex items-center justify-between text-[11px]"><span>{label}</span><span className="text-slate-500">{value}</span></div><div className="mt-1.5 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{width:value}}/></div><p className="mt-1 text-[9px] text-slate-600">{note}</p></div>;
}
export function SelectLike({ label, value }: any) {
  return <div><p className="mb-1 text-[10px] text-slate-600">{label}</p><div className="flex items-center justify-between rounded-lg border border-line bg-slate-950/40 px-3 py-2.5 text-[11px] text-slate-300">{value}<ChevronRight size={13} className="rotate-90 text-slate-600"/></div></div>;
}
export function Constraint({ title, value, status }: any) {
  return <div className="rounded-xl border border-line bg-slate-950/30 p-3"><div className="flex items-center justify-between"><span className="text-xs">{title}</span><span className="text-[10px] text-slate-500">{status}</span></div><div className="mt-2 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{width:value}}/></div><p className="mt-1 text-right text-[9px] text-slate-600">{value}</p></div>;
}
