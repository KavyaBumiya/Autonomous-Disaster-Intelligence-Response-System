import React from "react";

export interface KPIItem {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  tone?: "default" | "cyan" | "amber" | "red";
  progress?: number;
}

const toneValue: Record<NonNullable<KPIItem["tone"]>, string> = {
  default: "",
  cyan: "text-[#38d9c4]",
  amber: "text-[#f3b562]",
  red: "text-[#ff6b6b]",
};

export const KPIStrip: React.FC<{ items: KPIItem[] }> = ({ items }) => (
  <section className="ops-kpi-grid mb-6" aria-label="Key metrics">
    {items.map((item, i) => (
      <div className="ops-stat fade-in" key={item.label} style={{ animationDelay: `${i * 60}ms` }}>
        <div className="ops-stat-label">{item.label}</div>
        <div className={`ops-stat-value ${toneValue[item.tone || "default"]}`}>{item.value}</div>
        {typeof item.progress === "number" && (
          <div className="ops-progress mt-2">
            <span style={{ width: `${Math.max(0, Math.min(100, item.progress))}%` }} />
          </div>
        )}
        {item.detail && <div className="mt-2 text-xs text-slate-400">{item.detail}</div>}
      </div>
    ))}
  </section>
);
