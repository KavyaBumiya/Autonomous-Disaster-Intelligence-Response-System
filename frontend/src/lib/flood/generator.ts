import type { FloodReading, FloodScenario } from "./types";

const BASE_TIMESTAMP = new Date("2026-09-29T09:30:00");

function makeReading(
  waterLevel: number,
  flowVelocity: number,
  stepIndex: number,
): FloodReading {
  const ts = new Date(BASE_TIMESTAMP.getTime() + stepIndex * 5000);
  return {
    water_level: Math.round(waterLevel * 100) / 100,
    flow_velocity: Math.round(flowVelocity * 100) / 100,
    timestamp: ts.toISOString(),
  };
}

export function generateScenario(
  scenario: FloodScenario,
  steps: number = 20,
): FloodReading[] {
  const readings: FloodReading[] = [];

  switch (scenario) {
    case "NORMAL":
      for (let i = 0; i < steps; i++) {
        readings.push(makeReading(1.0 + Math.sin(i * 0.5) * 0.2, 0.5 + Math.sin(i * 0.5) * 0.15, i));
      }
      break;

    case "RISING_WATER":
      for (let i = 0; i < steps; i++) {
        const t = i / (steps - 1);
        const wl = 1.0 + t * 2.8;
        const fv = 0.5 + t * 2.0;
        readings.push(makeReading(wl, fv, i));
      }
      break;

    case "HIGH_FLOW":
      for (let i = 0; i < steps; i++) {
        const t = i / (steps - 1);
        const wl = 1.5 + t * 1.5;
        const fv = 0.8 + t * 2.7;
        readings.push(makeReading(wl, fv, i));
      }
      break;

    case "FLOOD":
      for (let i = 0; i < steps; i++) {
        const t = i / (steps - 1);
        const wl = 1.0 + t * 3.2;
        const fv = 0.5 + t * 2.8;
        readings.push(makeReading(wl, fv, i));
      }
      break;

    case "RECOVERY":
      for (let i = 0; i < steps; i++) {
        const t = i / (steps - 1);
        const wl = 4.0 - t * 3.0;
        const fv = 3.2 - t * 2.7;
        readings.push(makeReading(Math.max(1.0, wl), Math.max(0.5, fv), i));
      }
      break;
  }

  return readings;
}

export function generateContinuousScenario(
  scenario: FloodScenario,
  tick: number,
): FloodReading {
  const cycleLength = 40;
  const t = (tick % cycleLength) / cycleLength;

  switch (scenario) {
    case "NORMAL":
      return makeReading(
        1.0 + Math.sin(t * Math.PI * 4) * 0.2,
        0.5 + Math.sin(t * Math.PI * 4) * 0.15,
        tick,
      );

    case "RISING_WATER":
      return makeReading(1.0 + t * 2.8, 0.5 + t * 2.0, tick);

    case "HIGH_FLOW":
      return makeReading(1.5 + t * 1.5, 0.8 + t * 2.7, tick);

    case "FLOOD":
      return makeReading(1.0 + t * 3.2, 0.5 + t * 2.8, tick);

    case "RECOVERY":
      return makeReading(
        Math.max(1.0, 4.0 - t * 3.0),
        Math.max(0.5, 3.2 - t * 2.7),
        tick,
      );
  }
}
