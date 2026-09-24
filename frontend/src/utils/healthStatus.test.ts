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
  groq: "ONLINE" as const,
  predictions: "ONLINE" as const,
  maps: "ONLINE" as const,
  realtime: "ONLINE" as const,
  checking: false,
};

describe("calculateOverallHealth", () => {
  it("TEST 1: API healthy + Groq healthy → ONLINE", () => {
    expect(calculateOverallHealth(allOnline)).toBe("ONLINE");
  });

  it("TEST 2: API healthy + Groq unavailable → DEGRADED", () => {
    expect(
      calculateOverallHealth({ ...allOnline, groq: "OFFLINE" }),
    ).toBe("DEGRADED");
    expect(
      calculateOverallHealth({ ...allOnline, groq: "DEGRADED" }),
    ).toBe("DEGRADED");
  });

  it("TEST 3: API unavailable + Groq healthy → OFFLINE", () => {
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
    // Groq still unknown after checks → incomplete, not DEGRADED
    expect(
      calculateOverallHealth({
        ...allOnline,
        groq: "UNKNOWN",
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

  it("TEST 8: command/health unavailable → Groq offline, API independent → DEGRADED", () => {
    expect(
      calculateOverallHealth({
        ...allOnline,
        api: "ONLINE",
        groq: "OFFLINE",
      }),
    ).toBe("DEGRADED");
  });

  it("does not show DEGRADED while checking", () => {
    expect(
      calculateOverallHealth({
        ...allOnline,
        groq: "OFFLINE",
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
});

describe("getHealthReasons", () => {
  it("includes Groq reason when degraded but API online", () => {
    const reasons = getHealthReasons({
      ...allOnline,
      groq: "OFFLINE",
      overall: "DEGRADED",
    });
    expect(reasons.join(" ")).toMatch(/Groq AI unavailable/i);
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
});
