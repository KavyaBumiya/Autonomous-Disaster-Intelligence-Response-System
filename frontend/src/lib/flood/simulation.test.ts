import { describe, it, expect } from "vitest";
import {
  calculateFloodStatus,
  getWaterLevelBand,
  getFlowVelocityBand,
  getWaterLevelPercent,
  getFlowVelocityPercent,
  WATER_LEVEL_THRESHOLDS,
  FLOW_VELOCITY_THRESHOLDS,
} from "./simulation";
import { generateScenario, generateContinuousScenario } from "./generator";
import type { FloodReading } from "./types";

function reading(waterLevel: number, flowVelocity: number): FloodReading {
  return {
    water_level: waterLevel,
    flow_velocity: flowVelocity,
    timestamp: "2026-09-29T09:30:00",
  };
}

describe("getWaterLevelBand", () => {
  it("returns LOW for levels below threshold", () => {
    expect(getWaterLevelBand(0.5)).toBe("LOW");
    expect(getWaterLevelBand(1.4)).toBe("LOW");
  });

  it("returns MEDIUM for medium levels", () => {
    expect(getWaterLevelBand(1.5)).toBe("MEDIUM");
    expect(getWaterLevelBand(2.4)).toBe("MEDIUM");
  });

  it("returns HIGH for high levels", () => {
    expect(getWaterLevelBand(2.5)).toBe("HIGH");
    expect(getWaterLevelBand(3.4)).toBe("HIGH");
  });

  it("returns CRITICAL for critical levels", () => {
    expect(getWaterLevelBand(3.5)).toBe("CRITICAL");
    expect(getWaterLevelBand(5.0)).toBe("CRITICAL");
  });
});

describe("getFlowVelocityBand", () => {
  it("returns LOW for low velocities", () => {
    expect(getFlowVelocityBand(0.2)).toBe("LOW");
    expect(getFlowVelocityBand(0.9)).toBe("LOW");
  });

  it("returns MEDIUM for medium velocities", () => {
    expect(getFlowVelocityBand(1.0)).toBe("MEDIUM");
    expect(getFlowVelocityBand(1.9)).toBe("MEDIUM");
  });

  it("returns HIGH for high velocities", () => {
    expect(getFlowVelocityBand(2.0)).toBe("HIGH");
    expect(getFlowVelocityBand(2.9)).toBe("HIGH");
  });

  it("returns CRITICAL for critical velocities", () => {
    expect(getFlowVelocityBand(3.0)).toBe("CRITICAL");
    expect(getFlowVelocityBand(5.0)).toBe("CRITICAL");
  });
});

describe("calculateFloodStatus", () => {
  it("returns NORMAL when both values are low", () => {
    expect(calculateFloodStatus(reading(1.0, 0.5))).toBe("NORMAL");
  });

  it("returns WARNING when water level is medium", () => {
    expect(calculateFloodStatus(reading(1.8, 0.5))).toBe("WARNING");
  });

  it("returns WARNING when flow velocity is medium", () => {
    expect(calculateFloodStatus(reading(1.0, 1.5))).toBe("WARNING");
  });

  it("returns WARNING when water level is high", () => {
    expect(calculateFloodStatus(reading(2.8, 0.5))).toBe("WARNING");
  });

  it("returns CRITICAL when water level is critical", () => {
    expect(calculateFloodStatus(reading(4.0, 0.5))).toBe("CRITICAL");
  });

  it("returns CRITICAL when flow velocity is critical", () => {
    expect(calculateFloodStatus(reading(1.0, 3.5))).toBe("CRITICAL");
  });

  it("takes the maximum severity from both bands", () => {
    expect(calculateFloodStatus(reading(3.8, 1.0))).toBe("CRITICAL");
    expect(calculateFloodStatus(reading(1.0, 3.8))).toBe("CRITICAL");
  });
});

describe("getWaterLevelPercent", () => {
  it("returns 0 for zero", () => {
    expect(getWaterLevelPercent(0)).toBe(0);
  });

  it("returns 100 for max display value", () => {
    expect(getWaterLevelPercent(10)).toBe(100);
  });

  it("returns proportional percentage", () => {
    const maxDisplay = WATER_LEVEL_THRESHOLDS.HIGH + 0.5;
    expect(getWaterLevelPercent(maxDisplay / 2)).toBeCloseTo(50, 0);
  });
});

describe("getFlowVelocityPercent", () => {
  it("returns 0 for zero", () => {
    expect(getFlowVelocityPercent(0)).toBe(0);
  });

  it("returns 100 for max display value", () => {
    expect(getFlowVelocityPercent(10)).toBe(100);
  });

  it("returns proportional percentage", () => {
    const maxDisplay = FLOW_VELOCITY_THRESHOLDS.HIGH + 0.5;
    expect(getFlowVelocityPercent(maxDisplay / 2)).toBeCloseTo(50, 0);
  });
});

describe("generateScenario", () => {
  it("generates NORMAL scenario with low values", () => {
    const readings = generateScenario("NORMAL", 10);
    expect(readings).toHaveLength(10);
    for (const r of readings) {
      expect(r.water_level).toBeLessThan(1.5);
      expect(r.flow_velocity).toBeLessThan(1.0);
    }
  });

  it("generates RISING_WATER scenario with increasing values", () => {
    const readings = generateScenario("RISING_WATER", 10);
    expect(readings).toHaveLength(10);
    const first = readings[0];
    const last = readings[readings.length - 1];
    expect(last.water_level).toBeGreaterThan(first.water_level);
    expect(last.flow_velocity).toBeGreaterThan(first.flow_velocity);
  });

  it("generates FLOOD scenario with high values", () => {
    const readings = generateScenario("FLOOD", 10);
    const last = readings[readings.length - 1];
    expect(last.water_level).toBeGreaterThanOrEqual(3.5);
    expect(last.flow_velocity).toBeGreaterThanOrEqual(3.0);
  });

  it("generates RECOVERY scenario with decreasing values", () => {
    const readings = generateScenario("RECOVERY", 10);
    const first = readings[0];
    const last = readings[readings.length - 1];
    expect(last.water_level).toBeLessThan(first.water_level);
    expect(last.flow_velocity).toBeLessThan(first.flow_velocity);
  });

  it("produces valid FloodReading objects", () => {
    const readings = generateScenario("FLOOD", 5);
    for (const r of readings) {
      expect(typeof r.water_level).toBe("number");
      expect(typeof r.flow_velocity).toBe("number");
      expect(typeof r.timestamp).toBe("string");
      expect(Number.isNaN(Date.parse(r.timestamp))).toBe(false);
    }
  });

  it("produces deterministic results for same scenario", () => {
    const a = generateScenario("FLOOD", 10);
    const b = generateScenario("FLOOD", 10);
    expect(a).toEqual(b);
  });
});

describe("generateContinuousScenario", () => {
  it("produces different values for different ticks", () => {
    const a = generateContinuousScenario("FLOOD", 0);
    const b = generateContinuousScenario("FLOOD", 10);
    expect(a.water_level).not.toBe(b.water_level);
  });

  it("produces valid FloodReading objects", () => {
    const r = generateContinuousScenario("NORMAL", 5);
    expect(typeof r.water_level).toBe("number");
    expect(typeof r.flow_velocity).toBe("number");
    expect(typeof r.timestamp).toBe("string");
  });
});
