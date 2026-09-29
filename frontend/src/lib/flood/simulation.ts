import type {
  FloodReading,
  FloodStatus,
  WaterLevelBand,
  FlowVelocityBand,
} from "./types";

export const WATER_LEVEL_THRESHOLDS = {
  LOW: 1.5,
  MEDIUM: 2.5,
  HIGH: 3.5,
} as const;

export const FLOW_VELOCITY_THRESHOLDS = {
  LOW: 1.0,
  MEDIUM: 2.0,
  HIGH: 3.0,
} as const;

export function getWaterLevelBand(level: number): WaterLevelBand {
  if (level >= WATER_LEVEL_THRESHOLDS.HIGH) return "CRITICAL";
  if (level >= WATER_LEVEL_THRESHOLDS.MEDIUM) return "HIGH";
  if (level >= WATER_LEVEL_THRESHOLDS.LOW) return "MEDIUM";
  return "LOW";
}

export function getFlowVelocityBand(velocity: number): FlowVelocityBand {
  if (velocity >= FLOW_VELOCITY_THRESHOLDS.HIGH) return "CRITICAL";
  if (velocity >= FLOW_VELOCITY_THRESHOLDS.MEDIUM) return "HIGH";
  if (velocity >= FLOW_VELOCITY_THRESHOLDS.LOW) return "MEDIUM";
  return "LOW";
}

const BAND_SEVERITY: Record<WaterLevelBand | FlowVelocityBand, number> = {
  LOW: 0,
  MEDIUM: 1,
  HIGH: 2,
  CRITICAL: 3,
};

export function calculateFloodStatus(reading: FloodReading): FloodStatus {
  const waterBand = getWaterLevelBand(reading.water_level);
  const flowBand = getFlowVelocityBand(reading.flow_velocity);
  const maxSeverity = Math.max(
    BAND_SEVERITY[waterBand],
    BAND_SEVERITY[flowBand],
  );
  if (maxSeverity >= 3) return "CRITICAL";
  if (maxSeverity >= 1) return "WARNING";
  return "NORMAL";
}

export function getWaterLevelPercent(waterLevel: number): number {
  const maxDisplay = WATER_LEVEL_THRESHOLDS.HIGH + 0.5;
  return Math.min(100, Math.max(0, (waterLevel / maxDisplay) * 100));
}

export function getFlowVelocityPercent(flowVelocity: number): number {
  const maxDisplay = FLOW_VELOCITY_THRESHOLDS.HIGH + 0.5;
  return Math.min(100, Math.max(0, (flowVelocity / maxDisplay) * 100));
}
