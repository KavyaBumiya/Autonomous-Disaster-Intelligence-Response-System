/**
 * Parse the decision engine's factor breakdown out of `Incident.xai_reasoning`.
 *
 * `engine/decision.py` emits a fixed-width block like:
 *
 *   [30%] Victim Severity      12.3 pts  (60 victims, severity 70/100)
 *   [20%] People/Corroboration  5.0 pts  (12 reports, avg trust 0.80)
 *
 * The map's XAI overlay shows the single largest contributor per incident.
 * This is deliberately parsed from text already present on GET /api/incidents
 * rather than calling GET /api/command/explain per incident, which would fan
 * out into one LLM narrative call per incident.
 */

export interface XaiFactor {
  /** Human-readable factor name, e.g. "Victim Severity". */
  name: string;
  /** Points this factor contributed to the 0-100 priority score. */
  points: number;
  /** The PRD formula weight, e.g. 30 for the "[30%]" prefix. */
  weightPct: number;
}

const FACTOR_LINE = /^\s*\[(\d+)%\]\s+(.+?)\s+(\d+(?:\.\d+)?)\s*pts\b/;

/** Extract every factor line from an `xai_reasoning` block. */
export function parseXaiFactors(reasoning: string | null | undefined): XaiFactor[] {
  if (!reasoning) return [];
  const factors: XaiFactor[] = [];

  for (const line of reasoning.split("\n")) {
    const match = FACTOR_LINE.exec(line);
    if (!match) continue;
    const [, weightPct, name, points] = match;
    const parsedPoints = Number.parseFloat(points);
    if (!Number.isFinite(parsedPoints)) continue;
    factors.push({
      name: name.trim(),
      points: parsedPoints,
      weightPct: Number.parseInt(weightPct, 10),
    });
  }

  return factors;
}

/**
 * The factor that moved the priority score most.
 *
 * Ties break towards the higher PRD weight, then towards declaration order in
 * the block, so the result is stable across refetches.
 */
export function topXaiFactor(
  reasoning: string | null | undefined,
): XaiFactor | null {
  const factors = parseXaiFactors(reasoning);
  if (factors.length === 0) return null;

  return factors.reduce((best, current) => {
    if (current.points > best.points) return current;
    if (current.points < best.points) return best;
    return current.weightPct > best.weightPct ? current : best;
  });
}

/** Compact map label, e.g. "Victim Severity +12.3". */
export function formatXaiFactor(factor: XaiFactor | null): string {
  if (!factor) return "";
  return `${factor.name} +${factor.points.toFixed(1)}`;
}
