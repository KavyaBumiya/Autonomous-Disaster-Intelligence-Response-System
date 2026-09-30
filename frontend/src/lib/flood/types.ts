export type FloodReading = {
  water_level: number;
  flow_velocity: number;
  timestamp: string;
  risk_level?: string | null;
};

export type FloodStatus = "NORMAL" | "WARNING" | "CRITICAL" | "OFFLINE";

export type FloodScenario =
  | "NORMAL"
  | "RISING_WATER"
  | "HIGH_FLOW"
  | "FLOOD"
  | "RECOVERY";

export type SimulationSpeed = 0.5 | 1 | 2 | 5;

export type WaterLevelBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type FlowVelocityBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
