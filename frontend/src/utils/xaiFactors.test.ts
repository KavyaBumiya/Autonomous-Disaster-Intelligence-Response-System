import { describe, expect, it } from "vitest";

import {
  formatXaiFactor,
  parseXaiFactors,
  topXaiFactor,
} from "./xaiFactors";

/** Shape emitted verbatim by backend/app/engine/decision.py score_zone(). */
const REASONING = [
  "PRIORITY SCORE: 71.5/100  [HIGH]",
  "Confidence: 82%",
  "",
  "FACTOR BREAKDOWN (PRD §6 formula):",
  "  [30%] Victim Severity      12.3 pts  (60 victims, severity 70/100)",
  "  [20%] People/Corroboration  5.0 pts  (12 reports, avg trust 0.80)",
  "  [15%] Infrastructure Risk  3.0 pts  (weather risk 0.55 — light rain)",
  "  [15%] Hazard Severity      6.0 pts  (Detection Agent: 70/100)",
  "  [10%] Time Sensitivity     1.0 pts  (incident age 2.3h)",
  "  [10%] Prediction Risk      2.0 pts  (seismic 0.10, weather 0.55)",
  "",
  "ENVIRONMENTAL SIGNALS:",
  "  Weather: 12.5mm/hr rainfall, 30km/h wind  [HIGH]",
].join("\n");

describe("parseXaiFactors", () => {
  it("extracts every factor line from the breakdown block", () => {
    const factors = parseXaiFactors(REASONING);
    expect(factors).toHaveLength(6);
    expect(factors[0]).toEqual({
      name: "Victim Severity",
      points: 12.3,
      weightPct: 30,
    });
    expect(factors[3]).toEqual({
      name: "Hazard Severity",
      points: 6,
      weightPct: 15,
    });
  });

  it("keeps the factor name intact when the label contains spaces", () => {
    const [first] = parseXaiFactors(REASONING);
    expect(first.name).not.toContain("  ");
    expect(first.name).toBe("Victim Severity");
  });

  it("ignores narrative lines that are not factor rows", () => {
    const names = parseXaiFactors(REASONING).map((f) => f.name);
    expect(names).not.toContain("Confidence");
    expect(names.some((n) => n.includes("rainfall"))).toBe(false);
  });

  it("handles null, undefined and empty input", () => {
    expect(parseXaiFactors(null)).toEqual([]);
    expect(parseXaiFactors(undefined)).toEqual([]);
    expect(parseXaiFactors("")).toEqual([]);
  });

  it("returns nothing for text with no breakdown block", () => {
    expect(parseXaiFactors("Offline deterministic explanation.")).toEqual([]);
  });

  it("accepts integer points without a decimal part", () => {
    const factors = parseXaiFactors("  [50%] Some Factor  7 pts  (x)");
    expect(factors[0].points).toBe(7);
  });
});

describe("topXaiFactor", () => {
  it("picks the largest point contribution", () => {
    const top = topXaiFactor(REASONING);
    expect(top?.name).toBe("Victim Severity");
    expect(top?.points).toBe(12.3);
  });

  it("breaks point ties towards the higher PRD weight", () => {
    const top = topXaiFactor(
      [
        "  [15%] Lower Weight  5.0 pts  (a)",
        "  [30%] Higher Weight  5.0 pts  (b)",
      ].join("\n"),
    );
    expect(top?.name).toBe("Higher Weight");
  });

  it("keeps the earlier factor when points and weight are equal", () => {
    const top = topXaiFactor(
      [
        "  [20%] First  4.0 pts  (a)",
        "  [20%] Second 4.0 pts  (b)",
      ].join("\n"),
    );
    expect(top?.name).toBe("First");
  });

  it("returns null when there is no parsable breakdown", () => {
    expect(topXaiFactor(null)).toBeNull();
    expect(topXaiFactor("no factors here")).toBeNull();
  });

  it("picks the last factor when it is genuinely the largest", () => {
    const top = topXaiFactor(
      [
        "  [10%] Small       1.0 pts  (a)",
        "  [10%] Largest    41.5 pts  (b)",
      ].join("\n"),
    );
    expect(top?.name).toBe("Largest");
    expect(top?.points).toBe(41.5);
  });
});

describe("formatXaiFactor", () => {
  it("renders a one-decimal signed contribution", () => {
    expect(
      formatXaiFactor({ name: "Victim Severity", points: 12.3, weightPct: 30 }),
    ).toBe("Victim Severity +12.3");
  });

  it("returns an empty string when there is no factor", () => {
    expect(formatXaiFactor(null)).toBe("");
  });
});
