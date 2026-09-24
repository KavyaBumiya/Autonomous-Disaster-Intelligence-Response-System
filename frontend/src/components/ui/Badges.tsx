import React from "react";

type Tone = "cyan" | "amber" | "red" | "blue" | "violet" | "slate";

const toneClass: Record<Tone, string> = {
  cyan: "ops-badge-cyan",
  amber: "ops-badge-amber",
  red: "ops-badge-red",
  blue: "ops-badge-blue",
  violet: "ops-badge-violet",
  slate: "ops-badge-slate",
};

export const Badge: React.FC<{
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
  title?: string;
}> = ({ tone = "slate", children, className = "", title }) => (
  <span className={`ops-badge ${toneClass[tone]} ${className}`} title={title}>
    {children}
  </span>
);

export const StatusBadge: React.FC<{ status?: string | null; label?: string }> = ({
  status,
  label,
}) => {
  const s = (status || "").toLowerCase();
  const tone: Tone =
    s === "available" || s === "ok" || s === "online" || s === "active"
      ? "cyan"
      : s === "offline" || s === "error"
        ? "red"
        : s === "degraded" || s === "pending" || s === "in_use"
          ? "amber"
          : "slate";
  return <Badge tone={tone}>{label || status || "unknown"}</Badge>;
};

const priorityTone = (score: number): Tone =>
  score >= 70 ? "red" : score >= 40 ? "amber" : "cyan";

export const PriorityBadge: React.FC<{ score?: number | null; band?: string | null }> = ({
  score,
  band,
}) => {
  const n = score ?? 0;
  const tone = priorityTone(n);
  return (
    <Badge tone={tone} title={`Priority ${n.toFixed(0)}/100`}>
      {band || `${n.toFixed(0)}/100`}
    </Badge>
  );
};

export const ConfidenceBadge: React.FC<{ value?: number | null }> = ({ value }) => {
  const n = value ?? 0;
  const pct = Math.round(n * 100);
  const tone: Tone = n >= 0.7 ? "cyan" : n >= 0.4 ? "amber" : "red";
  return <Badge tone={tone}>{pct}% conf</Badge>;
};

export const ResourceStatusBadge: React.FC<{
  available?: boolean;
  currentLoad?: number | null;
  capacity?: number | null;
}> = ({ available, currentLoad, capacity }) => {
  const isAvail = available === true && (currentLoad ?? 0) < (capacity ?? 0);
  return (
    <Badge tone={isAvail ? "cyan" : "amber"}>{isAvail ? "ready" : "in use"}</Badge>
  );
};
