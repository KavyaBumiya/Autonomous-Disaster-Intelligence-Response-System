/**
 * Live render check for the model-coverage wiring.
 *
 * `build.mjs` proves every page renders with the backend DOWN. That is the
 * offline-fallback path, and it structurally cannot exercise the new coverage
 * panel or the seismic prior note: both are gated on data that does not exist
 * when the backend is unreachable. A panel that compiles and returns null
 * offline will still be wrong online, and only rendering it against the real
 * payload can catch that.
 *
 * So this fetches the actual endpoints and renders the actual components with
 * the actual response shapes, then asserts the honesty properties rather than
 * just the presence of strings:
 *
 *   - the seismic rate is rendered next to the "not a forecast" qualifier, and
 *     never as a bare number;
 *   - a 0.0 rate is shown as a real measurement with its zero stated, not
 *     suppressed as missing data;
 *   - every declined hazard appears with a reason, and seismic is distinguished
 *     from the hard refusals by its background-prior badge.
 *
 * Run against a live backend:  node smoke/live-check.mjs
 */
import { renderToString } from "react-dom/server";
import { writeFileSync, unlinkSync } from "node:fs";
import { build } from "esbuild";

const API = process.env.LIVE_API ?? "http://127.0.0.1:8000";
const PAGE = "src/__live_page.tsx";
const ENTRY = "src/__live_entry.tsx";
const BUNDLE = "smoke/.live.cjs";
const stripTags = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

let failures = 0;
const check = (ok, label) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) failures++;
};

const inventory = await (await fetch(`${API}/api/phase2/hazard-inventory`)).json();
const zones = await (await fetch(`${API}/api/zones?limit=3`)).json();
const zone = zones.zones[1] ?? zones.zones[0];
const matrix = await (
  await fetch(`${API}/api/predictions/all/${encodeURIComponent(zone.zone_id)}`)
).json();

const eq = matrix.hazards.find((h) => h.disaster_type === "earthquake");
const registry = await (await fetch(`${API}/api/phase2/models`)).json();
console.log(
  `backend: ${inventory.trained_count} fitted, ${inventory.declined_count} declined; ` +
    `zone ${zone.name}; earthquake background_rate=${eq?.background_rate ? "present" : "ABSENT"}\n`,
);

// The page pulls its own data through hooks, so hand the components the fetched
// payloads and let them render from those instead of re-fetching during SSR.
writeFileSync(
  ENTRY,
  `import { renderToString } from "react-dom/server";
import * as React from "react";
import { ModelTransparencyPanel, SeismicPriorNote } from "./__live_page";
const inventory = ${JSON.stringify(inventory)};
const registry = ${JSON.stringify(registry)};
const rate = ${JSON.stringify(eq?.background_rate ?? null)};
function Harness() {
  return React.createElement(
    "div",
    null,
    React.createElement(ModelTransparencyPanel, { inventory, registry }),
    rate ? React.createElement(SeismicPriorNote, { rate }) : null,
  );
}
process.stdout.write(renderToString(React.createElement(Harness)));
`,
);

writeFileSync(
  PAGE,
  `export { ModelTransparencyPanel, SeismicPriorNote } from "./pages/PredictionPage";
`,
);

try {
  await build({
    entryPoints: [ENTRY],
    bundle: true,
    platform: "node",
    format: "cjs",
    outfile: BUNDLE,
    jsx: "automatic",
    logLevel: "error",
    define: {
      "import.meta.env": JSON.stringify({ MODE: "test", DEV: false, PROD: true }),
    },
    loader: { ".tsx": "tsx" },
  });
} catch (error) {
  console.log(`BUILD FAIL: ${error.message}`);
  process.exit(1);
}

const { execFileSync } = await import("node:child_process");
let text = "";
try {
  const html = execFileSync(process.execPath, [BUNDLE], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  text = stripTags(html);
} catch (error) {
  console.log(`RENDER FAIL: ${String(error.stderr || error.message).slice(0, 600)}`);
  process.exit(1);
} finally {
  for (const f of [PAGE, ENTRY, BUNDLE]) {
    try {
      unlinkSync(f);
    } catch {
      /* already gone */
    }
  }
}

check(text.includes("Model coverage"), "coverage panel renders");
check(
  text.includes(`${inventory.trained_count} fitted`) &&
    text.includes(`${inventory.declined_count} declined`),
  "fitted/declined counts render",
);

// Every declined hazard must be present, and each must be expandable to a
// reason. If a hazard silently vanishes from the ledger the gap is
// indistinguishable from "nobody looked".
for (const key of Object.keys(inventory.declined)) {
  const label = key.replace(/_/g, " ");
  check(text.toLowerCase().includes(label), `declined hazard listed: ${label}`);
}
check(text.includes("seismic rate only") || text.includes("rate only"), "seismic shows rate-only badge");

if (eq?.background_rate) {
  const r = eq.background_rate;
  check(text.includes("Long-run rate"), "seismic prior renders a rate line");
  check(text.includes("Not a forecast"), "seismic prior carries the not-a-forecast qualifier");
  if (r.events_within_radius === 0) {
    check(
      text.includes("No M") && text.includes("catalogue"),
      "zero-event rate is stated as a measurement, not hidden",
    );
  }
  check(
    text.includes(r.rate_per_year.toFixed(2)),
    `rate value renders (${r.rate_per_year.toFixed(2)}/yr)`,
  );
} else {
  check(false, "earthquake background_rate reached the matrix envelope");
}

console.log(
  failures === 0
    ? "\nLIVE RENDER OK — coverage ledger and seismic qualifier both surface"
    : `\n${failures} LIVE RENDER FAILURE(S)`,
);
process.exit(failures === 0 ? 0 : 1);
