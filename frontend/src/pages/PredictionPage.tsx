import { useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { useHazardInventory, useModelRegistry } from "../lib/hooks";
import { api } from "../lib/api";
import type {
  DeclinedHazardSpec,
  HazardInventoryResponse,
  HazardProjection,
  ModelRegistryEntry,
  SeismicBackgroundRate,
} from "../lib/types";
import { PageHeader, PanelTitle, MiniStat } from "../components/ui";

const { BrainCircuit, RefreshCw, CheckCircle2, Droplets, Flame, Activity, Users, Clock, TrendingUp, TrendingDown, Minus, AlertTriangle, Shield } = Icons;

interface ExplainState {
  priority: string;
  score: number;
  text: string;
}

interface PercentageBarProps {
  label: string;
  value: number;
  max?: number;
  color?: string;
  icon?: React.ReactNode;
  subtext?: string;
}

function PercentageBar({ label, value, max = 100, color = "bg-cyan", icon, subtext }: PercentageBarProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const numericValue = Math.round(value);
  return (
    <div className="rounded-lg border border-line bg-slate-950/30 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {icon && <span className="text-slate-400">{icon}</span>}
          <span className="text-xs font-medium text-slate-300">{label}</span>
        </div>
        <span className="text-sm font-bold text-white">{numericValue}%</span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {subtext && <p className="mt-1.5 text-[9px] text-slate-500">{subtext}</p>}
    </div>
  );
}

interface RiskGaugeProps {
  riskBand: string;
  confidence: number;
}

function RiskGauge({ riskBand, confidence }: RiskGaugeProps) {
  const isHigh = riskBand === "HIGH RISK";
  const isModerate = riskBand === "MODERATE RISK";
  const gaugeColor = isHigh ? "bg-danger" : isModerate ? "bg-amber" : "bg-success";
  const textColor = isHigh ? "text-danger" : isModerate ? "text-amber" : "text-success";

  return (
    <div className="rounded-xl border border-line bg-slate-950/30 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className={textColor} />
          <span className="text-xs font-semibold text-slate-200">Risk Assessment</span>
        </div>
        <span className={`chip !border-current/20 ${textColor}`}>{riskBand}</span>
      </div>
      <div className="mt-4 flex items-center gap-4">
        <div className="relative h-24 w-24 flex-shrink-0">
          <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" strokeWidth="8" className="text-slate-800" />
            <circle
              cx="50" cy="50" r="40" fill="none" strokeWidth="8"
              strokeDasharray={`${confidence * 2.51} 251`}
              className={`${gaugeColor} transition-all duration-700`}
              strokeLinecap="round"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-lg font-bold text-white">{Math.round(confidence)}%</span>
          </div>
        </div>
        <div className="flex-1 space-y-2">
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${gaugeColor}`} />
            <span className="text-[10px] text-slate-400">Model confidence</span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${isHigh ? "bg-danger" : isModerate ? "bg-amber" : "bg-success"}`} />
            <span className="text-[10px] text-slate-400">
              {isHigh ? "Immediate action required" : isModerate ? "Monitor closely" : "Situation stable"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * One hazard tile. An unavailable hazard reports its reason rather than showing
 * a confident zero, and its limitations are always visible — a projection with
 * unstated caveats is worse than no projection.
 */
function HazardCard({ hazard }: { hazard: HazardProjection }) {
  const accent = HAZARD_ACCENTS[hazard.disaster_type] ?? "text-slate-300";
  const bar = HAZARD_BARS[hazard.disaster_type] ?? "bg-slate-500";
  const intensity = Math.round(Math.max(0, Math.min(100, hazard.max_intensity)));
  const coverage =
    hazard.coverage_percentage === null
      ? null
      : Math.round(Math.max(0, Math.min(100, hazard.coverage_percentage)));
  const barWidth =
    hazard.modelled === "zone_uniform" || coverage === null ? intensity : coverage;

  return (
    <div className="rounded-lg border border-line bg-slate-950/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`h-2 w-2 flex-shrink-0 rounded-full ${bar}`} />
          <span className="truncate text-xs font-semibold text-slate-200">
            {hazard.display_name}
          </span>
        </div>
        {!hazard.available ? (
          <span className="chip flex-shrink-0 !border-slate-700 !text-slate-500">No signal</span>
        ) : (
          <span className={`text-sm font-bold ${accent}`}>{intensity}%</span>
        )}
      </div>

      {hazard.available ? (
        <>
          <div className="mt-2 h-2 rounded-full bg-slate-800">
            <div
              className={`h-full rounded-full transition-all duration-500 ${bar}`}
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <p className="mt-1.5 text-[9px] text-slate-500">
            {hazard.modelled === "zone_uniform"
              ? `Zone-wide intensity · ${hazard.cells.length} cell${hazard.cells.length === 1 ? "" : "s"}`
              : coverage === null
                ? `${hazard.cells.length} projected cell${hazard.cells.length === 1 ? "" : "s"}`
                : `${coverage}% of zone affected`}
          </p>
        </>
      ) : (
        <p className="mt-2 text-[9px] leading-relaxed text-slate-500">
          {hazard.reason ?? "No qualifying observation for this hazard."}
        </p>
      )}

      {hazard.background_rate ? (
        <SeismicPriorNote rate={hazard.background_rate} />
      ) : null}
    </div>
  );
}

/**
 * The long-run seismic rate, shown beside the live result but never merged
 * into it.
 *
 * The framing is deliberate and mirrors the backend's: this describes how active
 * the region has been, not what the next few hours hold. A 0.0/yr reading is
 * the honest answer for Gujarat and is worth stating plainly — it is not an
 * error and it is not a safety guarantee, since the catalogue only covers
 * M5.0+ and aftershocks are not declustered.
 */
export function SeismicPriorNote({ rate }: { rate: SeismicBackgroundRate }) {
  if (!rate.available) {
    return (
      <p className="mt-2 border-t border-line pt-2 text-[9px] text-slate-600">
        Background rate unavailable{rate.degradation_reason ? `: ${rate.degradation_reason}` : ""}
      </p>
    );
  }
  const perDecade = (rate.rate_per_year * 10).toFixed(1);
  return (
    <div className="mt-2 border-t border-line pt-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[9px] uppercase tracking-wide text-slate-600">
          Long-run rate
        </span>
        <span className="text-[10px] font-semibold text-slate-400">
          {rate.rate_per_year.toFixed(2)}/yr
        </span>
      </div>
      <p className="mt-1 text-[9px] leading-relaxed text-slate-600">
        {rate.events_within_radius === 0
          ? `No M${rate.min_magnitude.toFixed(1)}+ events within ${rate.radius_km} km in ${rate.catalogue_years.toFixed(1)} years of catalogue.`
          : `${rate.events_within_radius} M${rate.min_magnitude.toFixed(1)}+ events within ${rate.radius_km} km over ${rate.catalogue_years.toFixed(1)} years — about ${perDecade} per decade.`}
      </p>
      <p className="mt-1 text-[9px] leading-relaxed text-amber-500/80">
        Not a forecast. Regional activity, not a prediction for this window.
      </p>
    </div>
  );
}

const HAZARD_ACCENTS: Record<string, string> = {
  flood: "text-blue-400",
  fire: "text-orange-400",
  earthquake: "text-purple-400",
  landslide: "text-amber-400",
  storm: "text-cyan",
};

const HAZARD_BARS: Record<string, string> = {
  flood: "bg-blue-500",
  fire: "bg-orange-500",
  earthquake: "bg-purple-500",
  landslide: "bg-amber-500",
  storm: "bg-cyan",
};

/**
 * What is actually modelled, and what is deliberately not.
 *
 * This exists because a console showing five hazard tiles invites the reading
 * that five hazards are predicted. Two of them are rule-based, and four more
 * are absent entirely — lightning and severe weather among them. Listing the
 * refusals with their reasons turns a silent gap into a documented decision, and
 * `what_would_change_it` makes the blocker actionable rather than a dead end.
 */
export function ModelTransparencyPanel({
  inventory: inventoryOverride,
  registry: registryOverride,
}: {
  inventory?: HazardInventoryResponse | null;
  registry?: { models: Record<string, ModelRegistryEntry> } | null;
} = {}) {
  // Data may be injected so this can be rendered against a live payload in the
  // live-check harness; otherwise it is fetched by the hooks as normal.
  const liveInventory = useHazardInventory();
  const liveRegistry = useModelRegistry();
  const inventory = inventoryOverride !== undefined ? { data: inventoryOverride, isInitialLoading: false, error: null, lastUpdatedAt: 0, refresh: () => {} } : liveInventory;
  const registry = registryOverride !== undefined ? { data: registryOverride, isInitialLoading: false, error: null, lastUpdatedAt: 0, refresh: () => {} } : liveRegistry;
  const [openHazard, setOpenHazard] = useState<string | null>(null);

  if (inventory.isInitialLoading && !inventory.data) {
    return (
      <section className="panel p-4">
        <PanelTitle eyebrow="Coverage" title="Model coverage" />
        <p className="mt-3 text-[9px] text-slate-500">Loading coverage ledger…</p>
      </section>
    );
  }

  if (!inventory.data) {
    return null;
  }

  const { trained, declined, trained_count: trainedCount, declined_count: declinedCount } =
    inventory.data;
  const trainedList = Object.values(trained ?? {});
  const declinedList = Object.values(declined ?? {}).sort((a, b) =>
    a.key.localeCompare(b.key),
  );
  const models = registry.data?.models ?? {};
  const trainedModelMetrics = Object.entries(models).filter(([, m]) => m.trained);

  return (
    <section className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <PanelTitle eyebrow="Coverage" title="Model coverage" />
        <div className="flex flex-shrink-0 gap-1.5">
          <span className="chip !border-emerald-800 !text-emerald-400">{trainedCount} fitted</span>
          <span className="chip !border-slate-700 !text-slate-500">{declinedCount} declined</span>
        </div>
      </div>

      <p className="mt-2 text-[9px] leading-relaxed text-slate-500">
        A hazard absent from the projection grid is not a coverage gap — it was considered and
        declined, with the reason recorded in the source.
      </p>

      {trainedList.length > 0 && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {trainedList.map((spec) => {
            const metric = trainedModelMetrics.find(([name]) =>
              name.startsWith(spec.key),
            )?.[1];
            const auc = metric?.roc_auc;
            return (
              <div key={spec.key} className="rounded-lg border border-line bg-slate-950/30 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-semibold capitalize text-slate-200">
                    {spec.key}
                  </span>
                  {spec.rule_is_shipped ? (
                    <span
                      className="text-[8px] uppercase tracking-wide text-slate-500"
                      title="A deterministic rule ships alongside the model as the baseline it must beat"
                    >
                      +rule
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-[9px] text-slate-500">
                  {auc !== undefined
                    ? `ROC-AUC ${auc.toFixed(2)} · ${metric?.rows ?? 0} rows`
                    : `${spec.feature_columns.length} features · ${spec.antecedent_days}d window`}
                </p>
                {auc !== undefined && metric?.roc_auc_baseline_rule !== undefined ? (
                  <p
                    className={`mt-0.5 text-[9px] ${
                      auc > metric.roc_auc_baseline_rule ? "text-emerald-500" : "text-amber-500"
                    }`}
                  >
                    vs rule {auc > metric.roc_auc_baseline_rule ? "+" : ""}
                    {(auc - metric.roc_auc_baseline_rule).toFixed(3)}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {declinedList.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <p className="text-[9px] uppercase tracking-wide text-slate-600">Not modelled, on purpose</p>
          {declinedList.map((entry) => (
            <DeclinedRow
              key={entry.key}
              entry={entry}
              open={openHazard === entry.key}
              onToggle={() =>
                setOpenHazard((v) => (v === entry.key ? null : entry.key))
              }
            />
          ))}
        </div>
      )}
    </section>
  );
}

function DeclinedRow({
  entry,
  open,
  onToggle,
}: {
  entry: DeclinedHazardSpec;
  open: boolean;
  onToggle: () => void;
}) {
  const prior = entry.background_prior;
  return (
    <div className="rounded-lg border border-line bg-slate-950/20">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left"
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[10px] font-medium capitalize text-slate-400">
            {entry.key.replace(/_/g, " ")}
          </span>
          {prior?.available ? (
            <span
              className="chip flex-shrink-0 !border-purple-800 !text-purple-400"
              title="Not a forecast — a long-run regional rate"
            >
              rate only
            </span>
          ) : null}
        </span>
        <span className="flex-shrink-0 text-[9px] text-slate-600">{open ? "Hide" : "Why?"}</span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-line px-2.5 py-2">
          <p className="text-[9px] leading-relaxed text-slate-400">{entry.reason}</p>
          <div className="border-t border-line/60 pt-2">
            <p className="text-[9px] uppercase tracking-wide text-emerald-600">What would change it</p>
            <p className="mt-1 text-[9px] leading-relaxed text-slate-500">
              {entry.what_would_change_it}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function PredictionPage({ notify, refreshAll }: any) {
  const { forecastSeries, evidenceRows, predictionSummary, topIncident, predictions, hazardMatrix } = useConsoleData();
  const { riskBand, confidence, impactWindow, population, trend, floodPercent } = predictionSummary;
  const [explain, setExplain] = useState<ExplainState | null>(null);
  const [showLimitations, setShowLimitations] = useState(false);

  const hazards: HazardProjection[] = hazardMatrix?.hazards ?? [];

  const floodData = predictions?.last_flood;
  const fireData = predictions?.last_fire;
  const maxIntensity = floodData?.max_intensity ?? 0;
  const floodedPercentage = floodData?.flooded_percentage ?? 0;
  const victimConfidence = topIncident?.victim_confidence ?? 0;
  const reportTrust = topIncident?.avg_trust_score ?? 0;
  const incidentConfidence = topIncident?.confidence ?? 0;

  const confidenceNum = parseInt(confidence) || 0;
  const TrendIcon = trend === "Rising" ? TrendingUp : trend === "Falling" ? TrendingDown : Minus;
  const trendColor = trend === "Rising" ? "text-danger" : trend === "Falling" ? "text-success" : "text-slate-400";

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

  return (
    <>
      <PageHeader
        eyebrow="AI systems / Prediction Engine"
        title="Prediction engine"
        description="Forecast hazards, estimate impact windows, and expose evidence and confidence behind each prediction."
      >
        <span className="chip"><BrainCircuit size={12} className="text-cyan" /> Models healthy</span>
        <button onClick={() => { refreshAll(); notify("Prediction models refreshed"); }} className="icon-btn">
          <RefreshCw size={16} />
        </button>
      </PageHeader>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_340px]">
        {/* Left column — main prediction metrics */}
        <div className="space-y-4">
          {/* Risk gauge + key stats */}
          <section className="panel p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="eyebrow">Current forecast</p>
                <h2 className="mt-1 text-lg font-bold">Flash flood propagation</h2>
              </div>
              <span className="chip !border-danger/20 !text-danger">{riskBand}</span>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <RiskGauge riskBand={riskBand} confidence={confidenceNum} />

              <div className="grid grid-cols-2 gap-3">
                <MiniStat label="Impact window" value={impactWindow} />
                <MiniStat label="Population at risk" value={population} />
                <div className="rounded-lg border border-line bg-slate-950/30 p-3">
                  <p className="text-[9px] uppercase tracking-wider text-slate-600">Trend</p>
                  <div className="mt-1 flex items-center gap-1.5">
                    <TrendIcon size={14} className={trendColor} />
                    <span className="text-sm font-bold text-slate-200">{trend}</span>
                  </div>
                </div>
                <div className="rounded-lg border border-line bg-slate-950/30 p-3">
                  <p className="text-[9px] uppercase tracking-wider text-slate-600">Active incidents</p>
                  <p className="mt-1 text-sm font-bold text-slate-200">{topIncident?.report_count ?? 0}</p>
                </div>
              </div>
            </div>
          </section>

          {/* Prediction percentages — systematic grid */}
          <section className="panel p-4">
            <PanelTitle eyebrow="Model outputs" title="Prediction percentages" />
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <PercentageBar
                label="Flooded area"
                value={floodedPercentage}
                color="bg-blue-500"
                icon={<Droplets size={13} />}
                subtext="Projected inundation coverage"
              />
              <PercentageBar
                label="Max intensity"
                value={maxIntensity}
                color="bg-danger"
                icon={<Activity size={13} />}
                subtext="Peak flood depth index"
              />
              <PercentageBar
                label="Model confidence"
                value={confidenceNum}
                color="bg-cyan"
                icon={<BrainCircuit size={13} />}
                subtext="Overall prediction certainty"
              />
              <PercentageBar
                label="Victim detection"
                value={victimConfidence * 100}
                color="bg-amber"
                icon={<Users size={13} />}
                subtext="AI victim count confidence"
              />
              <PercentageBar
                label="Report trust"
                value={reportTrust * 100}
                color="bg-success"
                icon={<CheckCircle2 size={13} />}
                subtext="Avg. citizen report credibility"
              />
              <PercentageBar
                label="Incident confidence"
                value={incidentConfidence * 100}
                color="bg-purple-500"
                icon={<Shield size={13} />}
                subtext="Classification confidence"
              />
            </div>
          </section>

          {/* All-hazard matrix */}
          <section className="panel p-4">
            <div className="flex items-start justify-between gap-3">
              <PanelTitle eyebrow="All hazards" title="Multi-hazard projections" />
              {hazardMatrix && (
                <span className="chip flex-shrink-0">
                  {hazardMatrix.hazard_count} modelled
                </span>
              )}
            </div>

            {hazards.length === 0 ? (
              <div className="mt-4 rounded-lg border border-line bg-slate-950/30 p-4 text-center">
                <p className="text-xs text-slate-400">No hazard projections available.</p>
                <p className="mt-1 text-[9px] text-slate-500">
                  {hazardMatrix
                    ? "The prediction engine returned no hazards for this zone."
                    : "Waiting for the prediction engine to respond."}
                </p>
              </div>
            ) : (
              <>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {hazards.map((hazard) => (
                    <HazardCard key={hazard.disaster_type} hazard={hazard} />
                  ))}
                </div>

                <div className="mt-3 flex items-center justify-between">
                  <p className="text-[9px] text-slate-500">
                    {hazardMatrix?.projection_label ?? "MODEL PROJECTION"} ·{" "}
                    {hazardMatrix?.zone_name}
                  </p>
                  {hazards.some((h) => h.limitations.length > 0) && (
                    <button
                      onClick={() => setShowLimitations((v) => !v)}
                      className="text-[9px] font-medium text-amber-400 transition hover:text-amber-300"
                    >
                      {showLimitations ? "Hide" : "Show"} model limitations
                    </button>
                  )}
                </div>

                {showLimitations && (
                  <ul className="mt-2 space-y-1.5">
                    {hazards.map((hazard) =>
                      hazard.limitations.map((note) => (
                        <li
                          key={`${hazard.disaster_type}-${note}`}
                          className="flex gap-2 text-[9px] leading-relaxed text-slate-500"
                        >
                          <span className="flex-shrink-0 text-slate-600">
                            {hazard.disaster_type}
                          </span>
                          <span>{note}</span>
                        </li>
                      )),
                    )}
                  </ul>
                )}
              </>
            )}
          </section>

          <ModelTransparencyPanel />

          {/* Fire projection (if available) */}
          {fireData && (
            <section className="panel p-4">
              <PanelTitle eyebrow="Secondary model" title="Fire spread projection" />
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <PercentageBar
                  label="Burned area"
                  value={fireData.max_intensity}
                  color="bg-orange-500"
                  icon={<Flame size={13} />}
                  subtext="Projected burn coverage"
                />
                <div className="rounded-lg border border-line bg-slate-950/30 p-3">
                  <div className="flex items-center gap-2">
                    <TrendingUp size={13} className="text-slate-400" />
                    <span className="text-xs font-medium text-slate-300">Spread direction</span>
                  </div>
                  <p className="mt-2 text-sm font-bold text-white">{fireData.spread_direction_degrees}°</p>
                  <p className="mt-1 text-[9px] text-slate-500">Degrees from north</p>
                </div>
              </div>
            </section>
          )}

          {/* Forecast timeline */}
          <section className="panel p-4">
            <PanelTitle eyebrow="Temporal" title="Forecast timeline" />
            <div className="mt-5 flex items-end gap-2">
              {forecastSeries.map((v, i) => (
                <div key={i} className="flex-1">
                  <div
                    className="rounded-t bg-danger/60 transition-all duration-300"
                    style={{ height: `${Math.max(2, v * 1.6)}px` }}
                  />
                  <p className="mt-2 text-center text-[9px] text-slate-600">T+{i * 10}m</p>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Right column — evidence + decision trail */}
        <div className="space-y-4">
          <section className="panel p-4">
            <PanelTitle eyebrow="Evidence" title="Why the model believes this" />
            <div className="mt-3 space-y-2">
              {evidenceRows.map((row) => (
                <div key={row.label} className="rounded-lg border border-line p-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={13} className="text-success" />
                    <span className="text-xs font-semibold">{row.label}</span>
                    <span className="ml-auto text-[10px] font-medium text-slate-400">{row.confidence}</span>
                  </div>
                  <div className="mt-2 h-1.5 rounded-full bg-slate-800">
                    <div
                      className="h-full rounded-full bg-success/70 transition-all duration-500"
                      style={{ width: row.confidence }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <button
              onClick={openDecisionTrail}
              className="mt-4 w-full rounded-lg border border-cyan/20 bg-cyan/5 px-3 py-2.5 text-xs font-medium text-cyan transition hover:bg-cyan/10"
            >
              Open decision trail
            </button>
          </section>

          {/* Decision trail result */}
          {explain && (
            <section className="panel p-4">
              <PanelTitle eyebrow="XAI" title="Decision trail" />
              <div className="mt-3 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">Priority band</span>
                  <span className="chip">{explain.priority}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">Priority score</span>
                  <span className="text-sm font-bold text-white">{explain.score}</span>
                </div>
                <p className="text-[11px] leading-relaxed text-slate-300">{explain.text}</p>
              </div>
            </section>
          )}

          {/* Quick stats summary */}
          <section className="panel p-4">
            <PanelTitle eyebrow="Summary" title="Key figures" />
            <div className="mt-3 space-y-2.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500">Flooded percentage</span>
                <span className="font-bold text-white">{floodPercent}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500">Impact window</span>
                <span className="font-bold text-white">{impactWindow}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500">Population affected</span>
                <span className="font-bold text-white">{population}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500">Trend direction</span>
                <span className={`font-bold ${trendColor}`}>{trend}</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
