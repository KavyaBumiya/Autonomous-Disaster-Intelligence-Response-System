/**
 * Unit tests for calculateOverallHealth — pure rules, no network.
 * Run: npm test
 */
import { describe, expect, it } from "vitest";
import {
  calculateOverallHealth,
  createInitialHealth,
  getHealthReasons,
} from "./healthStatus";

const allOnline = {
  api: "ONLINE" as const,
  database: "ONLINE" as const,
  auth: "ONLINE" as const,
  ai: "ONLINE" as const,
  predictions: "ONLINE" as const,
  maps: "ONLINE" as const,
  realtime: "ONLINE" as const,
  weather: "ONLINE" as const,
  seismic: "ONLINE" as const,
  checking: false,
};

describe("calculateOverallHealth", () => {
  it("TEST 1: API healthy + NVIDIA healthy → ONLINE", () => {
    expect(calculateOverallHealth(allOnline)).toBe("ONLINE");
  });

  it("TEST 2: API healthy + NVIDIA unavailable → DEGRADED", () => {
    expect(
      calculateOverallHealth({ ...allOnline, ai: "OFFLINE" }),
    ).toBe("DEGRADED");
    expect(
      calculateOverallHealth({ ...allOnline, ai: "DEGRADED" }),
    ).toBe("DEGRADED");
  });

  it("TEST 3: API unavailable + NVIDIA healthy → OFFLINE", () => {
    expect(
      calculateOverallHealth({ ...allOnline, api: "OFFLINE" }),
    ).toBe("OFFLINE");
  });

  it("TEST 4: API healthy + realtime disconnected → DEGRADED", () => {
    expect(
      calculateOverallHealth({ ...allOnline, realtime: "DEGRADED" }),
    ).toBe("DEGRADED");
  });

  it("TEST 5: API healthy + map unavailable → DEGRADED", () => {
    expect(
      calculateOverallHealth({ ...allOnline, maps: "DEGRADED" }),
    ).toBe("DEGRADED");
  });

  it("TEST 6: initial loading → UNKNOWN (not DEGRADED)", () => {
    const initial = createInitialHealth();
    expect(calculateOverallHealth(initial)).toBe("UNKNOWN");
    expect(
      calculateOverallHealth({ ...allOnline, checking: true }),
    ).toBe("UNKNOWN");
    // NVIDIA still unknown after checks → incomplete, not DEGRADED
    expect(
      calculateOverallHealth({
        ...allOnline,
        ai: "UNKNOWN",
        checking: false,
      }),
    ).toBe("UNKNOWN");
    // When api still unknown before first check resolves:
    expect(
      calculateOverallHealth({
        ...allOnline,
        api: "UNKNOWN",
        checking: false,
      }),
    ).toBe("UNKNOWN");
  });

  it("TEST 7: unrelated endpoint failure does not force OFFLINE (API still ONLINE)", () => {
    // A 404 on heatmaps is not modeled as api OFFLINE
    expect(calculateOverallHealth(allOnline)).toBe("ONLINE");
    expect(calculateOverallHealth({ ...allOnline, predictions: "DEGRADED" })).toBe(
      "DEGRADED",
    );
  });

  it("TEST 8: command/health unavailable → NVIDIA offline, API independent → DEGRADED", () => {
    expect(
      calculateOverallHealth({
        ...allOnline,
        api: "ONLINE",
        ai: "OFFLINE",
      }),
    ).toBe("DEGRADED");
  });

  it("does not show DEGRADED while checking", () => {
    expect(
      calculateOverallHealth({
        ...allOnline,
        ai: "OFFLINE",
        checking: true,
      }),
    ).toBe("UNKNOWN");
  });

  it("auth REQUIRED alone does not OFFLINE; with maps config → DEGRADED", () => {
    expect(
      calculateOverallHealth({ ...allOnline, auth: "REQUIRED" }),
    ).toBe("ONLINE");
    expect(
      calculateOverallHealth({
        ...allOnline,
        auth: "REQUIRED",
        maps: "DEGRADED",
      }),
    ).toBe("DEGRADED");
  });

  it("TEST 9: weather provider degraded → DEGRADED (§31 optional service)", () => {
    expect(
      calculateOverallHealth({ ...allOnline, weather: "DEGRADED" }),
    ).toBe("DEGRADED");
    expect(
      calculateOverallHealth({ ...allOnline, weather: "OFFLINE" }),
    ).toBe("DEGRADED");
  });

  it("TEST 10: seismic provider degraded → DEGRADED, never OFFLINE overall", () => {
    expect(
      calculateOverallHealth({ ...allOnline, seismic: "DEGRADED" }),
    ).toBe("DEGRADED");
    // Overall can never go OFFLINE from an optional provider alone
    expect(
      calculateOverallHealth({ ...allOnline, seismic: "OFFLINE" }),
    ).toBe("DEGRADED");
  });

  it("TEST 11: weather/seismic UNKNOWN (no provider data yet) → still ONLINE", () => {
    expect(
      calculateOverallHealth({
        ...allOnline,
        weather: "UNKNOWN",
        seismic: "UNKNOWN",
      }),
    ).toBe("ONLINE");
  });
});

describe("getHealthReasons", () => {
  it("includes NVIDIA reason when degraded but API online", () => {
    const reasons = getHealthReasons({
      ...allOnline,
      ai: "OFFLINE",
      overall: "DEGRADED",
    });
    expect(reasons.join(" ")).toMatch(/NVIDIA AI unavailable/i);
    expect(reasons.join(" ")).toMatch(/remain online/i);
  });

  it("offline reason when API unreachable", () => {
    const reasons = getHealthReasons({
      ...allOnline,
      api: "OFFLINE",
      overall: "OFFLINE",
    });
    expect(reasons[0]).toMatch(/unreachable/i);
  });

  it("map config and auth reasons when applicable", () => {
    const reasons = getHealthReasons({
      ...allOnline,
      maps: "DEGRADED",
      auth: "REQUIRED",
      overall: "DEGRADED",
    });
    expect(reasons.join(" ")).toMatch(/Mapbox public token/i);
    expect(reasons.join(" ")).toMatch(/authentication required/i);
  });

  it("weather/seismic degraded reasons never claim fabricated data (§31)", () => {
    const reasons = getHealthReasons({
      ...allOnline,
      weather: "DEGRADED",
      seismic: "DEGRADED",
      overall: "DEGRADED",
    });
    expect(reasons.join(" ")).toMatch(/Weather provider degraded/i);
    expect(reasons.join(" ")).toMatch(/Seismic feed degraded/i);
    expect(reasons.join(" ")).toMatch(/never fabricated/i);
  });
});
