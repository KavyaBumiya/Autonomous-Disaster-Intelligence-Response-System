import { useEffect, useRef, useState, useCallback } from "react";
import {
  Droplets,
  Waves,
  Play,
  Pause,
  RotateCcw,
  Activity,
  Gauge,
  Clock,
  TrendingUp,
  AlertTriangle,
  AlertOctagon,
  CheckCircle2,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { FloodReading, FloodStatus, FloodScenario, SimulationSpeed } from "../lib/flood/types";
import { calculateFloodStatus, getWaterLevelPercent, getFlowVelocityPercent, getWaterLevelBand, getFlowVelocityBand } from "../lib/flood/simulation";
import { SimulationDataSource, type FloodDataSource } from "../lib/flood/source";
import { BackendDataSource } from "../lib/flood/backend-source";
import { generateScenario } from "../lib/flood/generator";
import { useHealth } from "../lib/hooks";
import { toFeedHealth } from "../lib/mappers";

const SCENARIOS: { value: FloodScenario; label: string }[] = [
  { value: "NORMAL", label: "Normal" },
  { value: "RISING_WATER", label: "Rising Water" },
  { value: "HIGH_FLOW", label: "High Flow" },
  { value: "FLOOD", label: "Flood" },
  { value: "RECOVERY", label: "Recovery" },
];

const SPEEDS: SimulationSpeed[] = [0.5, 1, 2, 5];

const STATUS_CONFIG: Record<FloodStatus, { icon: typeof CheckCircle2; color: string; bg: string; border: string; label: string }> = {
  NORMAL: { icon: CheckCircle2, color: "text-success", bg: "bg-success/10", border: "border-success/30", label: "NORMAL" },
  WARNING: { icon: AlertTriangle, color: "text-amber", bg: "bg-amber/10", border: "border-amber/30", label: "WARNING" },
  CRITICAL: { icon: AlertOctagon, color: "text-danger", bg: "bg-danger/10", border: "border-danger/30", label: "CRITICAL" },
  OFFLINE: { icon: WifiOff, color: "text-slate-400", bg: "bg-slate-500/10", border: "border-slate-500/30", label: "OFFLINE" },
};

const BAND_COLORS: Record<string, string> = {
  LOW: "bg-success",
  MEDIUM: "bg-cyan",
  HIGH: "bg-amber",
  CRITICAL: "bg-danger",
};

function WaterVisualization({ percent, status }: { percent: number; status: FloodStatus }) {
  const waterColor =
    status === "CRITICAL" ? "bg-danger" :
    status === "WARNING" ? "bg-amber" :
    status === "OFFLINE" ? "bg-slate-500" :
    "bg-cyan";

  return (
    <div className="relative h-48 w-full overflow-hidden rounded-xl border border-line bg-ink/60">
      <div className="absolute inset-x-0 bottom-0 flex items-end justify-center">
        <div
          className={`relative w-full transition-all duration-700 ease-in-out ${waterColor} opacity-80`}
          style={{ height: `${Math.max(8, percent)}%` }}
        >
          <div className="absolute inset-x-0 top-0 h-4 animate-pulse bg-white/20" />
          <div className="absolute inset-x-0 top-1 flex justify-center gap-8">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-1 w-8 rounded-full bg-white/30 animate-pulse" style={{ animationDelay: `${i * 200}ms` }} />
            ))}
          </div>
        </div>
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-3xl font-bold text-white drop-shadow-lg">
          {percent.toFixed(0)}%
        </span>
      </div>
      <div className="absolute bottom-2 left-3 text-[10px] uppercase tracking-wider text-white/50">
        Water Level
      </div>
      <div className="absolute bottom-2 right-3 text-[10px] uppercase tracking-wider text-white/50">
        {status}
      </div>
    </div>
  );
}

function FlowVisualization({ velocity, percent }: { velocity: number; percent: number }) {
  const arrowCount = Math.max(3, Math.min(12, Math.round(percent / 8)));
  const animationDuration = Math.max(0.3, 2 - velocity * 0.3);

  return (
    <div className="relative h-32 w-full overflow-hidden rounded-xl border border-line bg-ink/60">
      <div className="flex h-full flex-col items-center justify-center gap-2">
        <div className="flex items-center gap-1">
          {[...Array(arrowCount)].map((_, i) => (
            <span
              key={i}
              className="inline-block h-0.5 w-6 rounded bg-cyan transition-all"
              style={{
                animation: `flowRight ${animationDuration}s linear infinite`,
                animationDelay: `${i * 100}ms`,
              }}
            />
          ))}
        </div>
        <div className="flex items-center gap-1">
          {[...Array(arrowCount)].map((_, i) => (
            <span
              key={i}
              className="inline-block h-0.5 w-4 rounded bg-cyan/60 transition-all"
              style={{
                animation: `flowRight ${animationDuration * 1.2}s linear infinite`,
                animationDelay: `${i * 150 + 100}ms`,
              }}
            />
          ))}
        </div>
      </div>
      <div className="absolute bottom-2 left-3 text-[10px] uppercase tracking-wider text-white/50">
        Flow Velocity
      </div>
      <div className="absolute bottom-2 right-3 text-[10px] uppercase tracking-wider text-white/50">
        {velocity.toFixed(1)} m/s
      </div>
    </div>
  );
}

function HistoryChart({
  data,
  color,
  label,
  unit,
}: {
  data: FloodReading[];
  color: string;
  label: string;
  unit: string;
}) {
  const width = 300;
  const height = 80;
  const padding = 8;

  if (data.length < 2) {
    return (
      <div className="flex h-20 items-center justify-center rounded-lg border border-line bg-ink/40 text-xs text-slate-500">
        Collecting data...
      </div>
    );
  }

  const values = data.map((d) => d.water_level);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = data.map((d, i) => {
    const x = padding + (i / (data.length - 1)) * (width - padding * 2);
    const y = height - padding - ((d.water_level - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  }).join(" ");

  return (
    <div className="rounded-lg border border-line bg-ink/40 p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          {label}
        </span>
        <span className="text-[10px] text-slate-500">
          {data[data.length - 1]?.water_level.toFixed(2)} {unit}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-16 w-full">
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

function FlowHistoryChart({ data }: { data: FloodReading[] }) {
  const width = 300;
  const height = 80;
  const padding = 8;

  if (data.length < 2) {
    return (
      <div className="flex h-20 items-center justify-center rounded-lg border border-line bg-ink/40 text-xs text-slate-500">
        Collecting data...
      </div>
    );
  }

  const values = data.map((d) => d.flow_velocity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = data.map((d, i) => {
    const x = padding + (i / (data.length - 1)) * (width - padding * 2);
    const y = height - padding - ((d.flow_velocity - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  }).join(" ");

  return (
    <div className="rounded-lg border border-line bg-ink/40 p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Flow Velocity
        </span>
        <span className="text-[10px] text-slate-500">
          {data[data.length - 1]?.flow_velocity.toFixed(2)} m/s
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-16 w-full">
        <polyline
          points={points}
          fill="none"
          stroke="#39d9ff"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

type DataSourceMode = "simulation" | "backend";

export function FloodSimulation() {
  const dataSourceRef = useRef<FloodDataSource | null>(null);
  const backendSourceRef = useRef<BackendDataSource | null>(null);
  const backendUnsubRef = useRef<(() => void) | null>(null);
  const [reading, setReading] = useState<FloodReading | null>(null);
  const [history, setHistory] = useState<FloodReading[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [scenario, setScenario] = useState<FloodScenario>("NORMAL");
  const [speed, setSpeed] = useState<SimulationSpeed>(1);
  const [dataSourceMode, setDataSourceMode] = useState<DataSourceMode>("simulation");
  const [isStale, setIsStale] = useState(false);
  const health = useHealth();
  const feedHealth = toFeedHealth(health.data);
  const isSystemOnline = feedHealth.isNominal;

  useEffect(() => {
    const source = new SimulationDataSource();
    dataSourceRef.current = source;

    const unsubscribe = source.subscribe((r) => {
      setReading(r);
      setHistory((prev) => [...prev.slice(-30), r]);
    });

    const initialData = generateScenario("NORMAL", 5);
    setHistory(initialData);
    setReading(initialData[initialData.length - 1]);

    return () => {
      unsubscribe();
      source.pause();
      backendUnsubRef.current?.();
      backendUnsubRef.current = null;
      backendSourceRef.current?.disconnect();
      backendSourceRef.current = null;
    };
  }, []);

  const handleDataSourceToggle = useCallback((mode: DataSourceMode) => {
    if (mode === dataSourceMode) return;

    if (mode === "backend") {
      dataSourceRef.current?.pause();
      setIsRunning(false);
      // No hardcoded device id: the source resolves the enrolled device from
      // GET /api/iot/v1/devices, so Live mode works on any deployment that has
      // registered a sensor and reports "no data" when none is enrolled.
      const backend = new BackendDataSource();
      backendSourceRef.current = backend;
      // The returned cleanup was previously discarded, so every visit to this
      // page leaked one 5 s poller that kept hitting the API after unmount.
      backendUnsubRef.current = backend.subscribe((r) => {
        setReading(r);
        setIsStale(!r);
        setHistory((prev) => (r ? [...prev.slice(-30), r] : prev));
      });
      // Seed the history chart from stored telemetry so Live mode does not
      // start empty. Falls back to an empty chart if the device has no data.
      backend.getHistory(30).then((rows) => {
        if (rows.length > 0) setHistory(rows);
      }).catch(() => {});
    } else {
      backendUnsubRef.current?.();
      backendUnsubRef.current = null;
      backendSourceRef.current?.disconnect();
      backendSourceRef.current = null;
      const initialData = generateScenario(scenario, 5);
      setHistory(initialData);
      setReading(initialData[initialData.length - 1]);
    }
    setDataSourceMode(mode);
  }, [dataSourceMode, scenario]);

  const handleStart = useCallback(() => {
    dataSourceRef.current?.start();
    setIsRunning(true);
  }, []);

  const handlePause = useCallback(() => {
    dataSourceRef.current?.pause();
    setIsRunning(false);
  }, []);

  const handleReset = useCallback(() => {
    dataSourceRef.current?.reset();
    setIsRunning(false);
    const initialData = generateScenario(scenario, 5);
    setHistory(initialData);
    setReading(initialData[initialData.length - 1]);
  }, [scenario]);

  const handleScenarioChange = useCallback((newScenario: FloodScenario) => {
    setScenario(newScenario);
    dataSourceRef.current?.setScenario(newScenario);
    const initialData = generateScenario(newScenario, 5);
    setHistory(initialData);
    setReading(initialData[initialData.length - 1]);
  }, []);

  const handleSpeedChange = useCallback((newSpeed: SimulationSpeed) => {
    setSpeed(newSpeed);
    dataSourceRef.current?.setSpeed(newSpeed);
  }, []);

  const rawStatus = reading ? calculateFloodStatus(reading) : "NORMAL";
  const status = !isSystemOnline && rawStatus === "CRITICAL" ? "WARNING" : rawStatus;
  const displayStatus: FloodStatus = isStale && dataSourceMode === "backend" ? "OFFLINE" : status;
  const waterPercent = reading ? getWaterLevelPercent(reading.water_level) : 0;
  const flowPercent = reading ? getFlowVelocityPercent(reading.flow_velocity) : 0;
  const waterBand = reading ? getWaterLevelBand(reading.water_level) : "LOW";
  const flowBand = reading ? getFlowVelocityBand(reading.flow_velocity) : "LOW";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Simulation / IoT</p>
          <h2 className="text-xl font-bold text-white">Flood Simulation</h2>
          <p className="text-sm text-slate-400">
            Real-time flood monitoring simulation with configurable scenarios
          </p>
        </div>
        <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${STATUS_CONFIG[displayStatus].bg} ${STATUS_CONFIG[displayStatus].border} ${STATUS_CONFIG[displayStatus].color}`}>
          {(() => { const Icon = STATUS_CONFIG[displayStatus].icon; return <Icon size={14} />; })()}
          {displayStatus}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Droplets size={16} className="text-cyan" />
            <span className="text-sm font-semibold text-white">Water Level</span>
          </div>
          <div className="text-3xl font-bold text-white">
            {reading?.water_level.toFixed(2) ?? "--"}
            <span className="ml-1 text-sm font-normal text-slate-400">m</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${BAND_COLORS[waterBand]}`} />
            <span className="text-xs text-slate-400">{waterBand}</span>
          </div>
        </div>

        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Waves size={16} className="text-cyan" />
            <span className="text-sm font-semibold text-white">Flow Velocity</span>
          </div>
          <div className="text-3xl font-bold text-white">
            {reading?.flow_velocity.toFixed(2) ?? "--"}
            <span className="ml-1 text-sm font-normal text-slate-400">m/s</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${BAND_COLORS[flowBand]}`} />
            <span className="text-xs text-slate-400">{flowBand}</span>
          </div>
        </div>

        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Clock size={16} className="text-cyan" />
            <span className="text-sm font-semibold text-white">Last Reading</span>
          </div>
          <div className="text-3xl font-bold text-white">
            {reading ? new Date(reading.timestamp).toLocaleTimeString() : "--:--:--"}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            {reading ? new Date(reading.timestamp).toLocaleDateString() : ""}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Activity size={16} className="text-cyan" />
            <span className="text-sm font-semibold text-white">Flood Visualization</span>
          </div>
          <WaterVisualization percent={waterPercent} status={status} />
          <div className="mt-3">
            <FlowVisualization velocity={reading?.flow_velocity ?? 0} percent={flowPercent} />
          </div>
        </div>

        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Gauge size={16} className="text-cyan" />
            <span className="text-sm font-semibold text-white">Live Data Panel</span>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-line bg-ink/40 p-3">
              <span className="text-sm text-slate-400">Water Level</span>
              <span className="text-lg font-bold text-white">{reading?.water_level.toFixed(2)} m</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-line bg-ink/40 p-3">
              <span className="text-sm text-slate-400">Flow Velocity</span>
              <span className="text-lg font-bold text-white">{reading?.flow_velocity.toFixed(2)} m/s</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-line bg-ink/40 p-3">
              <span className="text-sm text-slate-400">Timestamp</span>
              <span className="text-sm font-mono text-white">
                {reading ? new Date(reading.timestamp).toLocaleTimeString() : "--"}
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-line bg-ink/40 p-3">
              <span className="text-sm text-slate-400">Simulation State</span>
              <span className={`text-sm font-semibold ${isRunning ? "text-success" : "text-slate-500"}`}>
                {isRunning ? "RUNNING" : "PAUSED"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <TrendingUp size={16} className="text-cyan" />
          <span className="text-sm font-semibold text-white">History</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <HistoryChart data={history} color="#35d39a" label="Water Level" unit="m" />
          <FlowHistoryChart data={history} />
        </div>
      </div>

      <div className="panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Activity size={16} className="text-cyan" />
          <span className="text-sm font-semibold text-white">Simulation Controls</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={isRunning ? handlePause : handleStart}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${
              isRunning
                ? "bg-amber text-ink hover:bg-amber/90"
                : "bg-success text-ink hover:bg-success/90"
            }`}
          >
            {isRunning ? <Pause size={16} /> : <Play size={16} />}
            {isRunning ? "PAUSE" : "START"}
          </button>
          <button
            onClick={handleReset}
            className="flex items-center gap-2 rounded-lg border border-line bg-slate-900/50 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:border-slate-600 hover:text-white"
          >
            <RotateCcw size={16} />
            RESET
          </button>
          <div className="h-6 w-px bg-line" />
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Source:</span>
            <div className="flex gap-1">
              <button
                onClick={() => handleDataSourceToggle("simulation")}
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                  dataSourceMode === "simulation"
                    ? "bg-cyan text-ink"
                    : "border border-line bg-slate-900/50 text-slate-400 hover:text-white"
                }`}
              >
                <WifiOff size={12} />
                Sim
              </button>
              <button
                onClick={() => handleDataSourceToggle("backend")}
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                  dataSourceMode === "backend"
                    ? "bg-cyan text-ink"
                    : "border border-line bg-slate-900/50 text-slate-400 hover:text-white"
                }`}
              >
                <Wifi size={12} />
                Live
              </button>
            </div>
          </div>
          {dataSourceMode === "backend" && (
            <span
              className={`text-[10px] ${
                reading ? "text-emerald-400" : "text-slate-500"
              }`}
            >
              {reading ? "sensor data received" : "no sensor data yet"}
            </span>
          )}
          <div className="h-6 w-px bg-line" />
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Scenario:</span>
            <select
              value={scenario}
              onChange={(e) => handleScenarioChange(e.target.value as FloodScenario)}
              className="rounded-lg border border-line bg-slate-900/50 px-3 py-1.5 text-sm text-white outline-none focus:border-cyan"
            >
              {SCENARIOS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Speed:</span>
            <div className="flex gap-1">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSpeedChange(s)}
                  className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                    speed === s
                      ? "bg-cyan text-ink"
                      : "border border-line bg-slate-900/50 text-slate-400 hover:text-white"
                  }`}
                >
                  {s}x
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
