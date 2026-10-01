/**
 * Offline-render smoke test.
 *
 * Renders every console page with the backend unreachable (the initial render
 * performs no effects, so each hook returns its "no data" state) and asserts
 * two things:
 *
 *   1. Each page still renders its full chrome — headings, panels, controls and
 *      primary calls to action survive a dead backend, so an operator can
 *      always see what the system *would* do and why a panel is empty.
 *
 *   2. None of the fabricated demo values this console used to ship with
 *      reappear. Showing "3,200 people at risk" or "42 min" when the read
 *      failed is the single most damaging failure mode for a command console:
 *      an operator cannot tell a plausible number from a real one. So the
 *      absent-data state must be absent-data, and this test fails loudly if a
 *      hard-coded figure is reintroduced anywhere.
 *
 * This is deliberately the inverse of the old assertion set, which required
 * those very demo strings to be present.
 */
import { renderToString } from "react-dom/server";
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { build } from "esbuild";

const PAGES = [
  "Overview",
  "Report Intake",
  "Live Map",
  "Incidents",
  "Resources",
  "Routes",
  "Teams",
  "Prediction Engine",
  "Resource Commander",
  "AI Assistant",
];

/** Strings each page must render with the backend down. */
const EXPECT = {
  Overview: [
    "Situation overview",
    "Active incidents",
    "Prediction confidence",
    "People at risk",
    "Units deployed",
    "Live operational map",
    "Operational capacity",
    "Rescue teams",
    "Ambulances",
    "Food kits",
    "Water units",
    "Incident feed",
    "Route intelligence",
    "Recommended movement",
    "No Emergency Yet",
    "AI recommendations are decision support",
  ],
  "Report Intake": [
    "Report intake",
    "Describe what is happening",
    "New signal",
    "Submit report",
    "Pipeline",
    "Processing status",
    "No report submitted in this session",
  ],
  "Live Map": [
    "Live operational map",
    "Map controls",
    "Selected zone",
    "Flood extent",
    "Prediction cone",
    "Citizen reports",
    "Team positions",
    "Shelters",
    "Incidents",
    "ETA",
    "People",
    "Confidence",
  ],
  Incidents: [
    "Incident command queue",
    "No incident selected",
    "Select an incident to view details",
    "AI assessment",
    "Create response workflow",
  ],
  Resources: [
    "Resource command",
    "Allocation queue",
    "Recommended allocations",
    "No pending AI allocations for the current incident",
    "Stock health",
    "Supply pressure",
    "Add resource",
  ],
  Routes: [
    "Route intelligence",
    "Mission routing",
    "Hazard type",
    "Blocked roads",
    "Compute routes",
    "Route insight",
    "Share with field teams",
  ],
  Teams: [
    "Field teams",
    "Team readiness",
    "Deployment capacity",
    "Available teams",
    "Deployed",
    "Standby",
    "Comms health",
    "Dispatch team",
  ],
  "Prediction Engine": [
    "Prediction engine",
    "Flash flood propagation",
    "Forecast timeline",
    "Why the model believes this",
    "River sensor trend",
    "Open decision trail",
    // Multi-hazard matrix. The backend is unreachable during this render, so
    // the panel must show its no-data state rather than a confident zero.
    "All hazards",
    "Multi-hazard projections",
    "No hazard projections available",
    "Waiting for the prediction engine to respond",
    "Prediction percentages",
    "Key figures",
  ],
  "Resource Commander": [
    "Resource Commander",
    "Allocation plan",
    "No actions are awaiting approval",
    "Constraint monitor",
    "What could block the plan",
    "Ambulance availability",
    "Rescue team coverage",
    "Water reserve",
    "Fuel stock",
    "Operator attention",
  ],
  "AI Assistant": [
    "Ask AegisAI",
    "Operational conversation",
    "Suggested prompts",
    "Trust layer",
    "Human confirmation required",
  ],
};

/**
 * Fabricated figures the console must never render on a failed read.
 *
 * These were hard-coded demo values in an earlier build. If any reappear, a
 * failed backend is being disguised as a live, quiet situation.
 */
const FORBIDDEN = [
  "3,200",
  "42 min",
  "94% confidence",
  "Flash flood risk",
  "Sabarmati river belt",
  "Rescue Team 04",
  "Medical Unit 07",
  "NGO Relief 12",
  "Rescue Team 09",
  "North rescue corridor",
  "Ashram Road",
  "Relief camp supply route",
  "Reserve 180 units",
  "2 rescue teams",
  "Pre-position 2 rescue teams near Ellis Bridge",
  "North corridor reduces expected response time by 11 minutes",
  "I’m monitoring the active Ahmedabad incident",
];

const SRC = "src/App.tsx";
const GENERATED_PAGE = "src/__smoke_page.tsx";
const GENERATED_ENTRY = "src/__smoke_entry.tsx";
// esbuild extracts the CSS import to a sidecar next to `outfile`, so the
// bundle is two files. Both are build output, not source.
const GENERATED_BUNDLE = "smoke/.page.cjs";
const GENERATED_BUNDLE_CSS = "smoke/.page.css";
const original = readFileSync(SRC, "utf8");

const stripTags = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

let failures = 0;

for (const page of PAGES) {
  // Same component, different landing nav item.
  const patched = original.replace(
    'useState<NavItem>("Overview")',
    `useState<NavItem>(${JSON.stringify(page)})`,
  );
  if (patched === original && page !== "Overview") {
    console.log(`SKIP  ${page} (could not patch initial nav)`);
    failures++;
    continue;
  }
  writeFileSync(GENERATED_PAGE, patched);
  // React and the SSR renderer must live in the SAME bundle, otherwise the
  // component and the renderer end up with different React instances.
  writeFileSync(
    GENERATED_ENTRY,
    `import { renderToString } from "react-dom/server";\n` +
      `import App from "./__smoke_page";\n` +
      `process.stdout.write(renderToString(<App />));\n`,
  );

  try {
    await build({
      entryPoints: [GENERATED_ENTRY],
      bundle: true,
      platform: "node",
      format: "cjs",
      outfile: GENERATED_BUNDLE,
      jsx: "automatic",
      logLevel: "error",
      define: {
        "import.meta.env": JSON.stringify({ MODE: "test", DEV: false, PROD: true }),
      },
      loader: { ".tsx": "tsx" },
    });
  } catch (error) {
    console.log(`BUILD FAIL  ${page}: ${error.message}`);
    failures++;
    continue;
  }

  const { execFileSync } = await import("node:child_process");
  let html = "";
  try {
    html = execFileSync(process.execPath, [GENERATED_BUNDLE], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    console.log(`RENDER FAIL  ${page}: ${String(error.stderr || error.message).slice(0, 300)}`);
    failures++;
    continue;
  }

  const text = stripTags(html);
  const missing = EXPECT[page].filter((probe) => !text.includes(probe));
  // Fabricated figures must never render, on any page.
  const leaked = FORBIDDEN.filter((probe) => text.includes(probe));

  if (missing.length === 0 && leaked.length === 0) {
    console.log(
      `PASS  ${page.padEnd(19)} (${html.length} bytes, ${EXPECT[page].length} chrome + ${FORBIDDEN.length} honesty probes)`,
    );
  } else {
    failures++;
    if (missing.length) console.log(`FAIL  ${page.padEnd(19)} missing: ${JSON.stringify(missing)}`);
    if (leaked.length) console.log(`FAIL  ${page.padEnd(19)} FABRICATED DATA RENDERED: ${JSON.stringify(leaked)}`);
  }
}

for (const file of [
  GENERATED_PAGE,
  GENERATED_ENTRY,
  GENERATED_BUNDLE,
  GENERATED_BUNDLE_CSS,
]) {
  try {
    unlinkSync(file);
  } catch {}
}

console.log(
  failures === 0
    ? `\nALL ${PAGES.length} PAGES RENDER HONESTLY WITH THE BACKEND DOWN`
    : `\n${failures} PAGE(S) FAILED`,
);
process.exit(failures === 0 ? 0 : 1);
