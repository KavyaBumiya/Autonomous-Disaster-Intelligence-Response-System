/**
 * Fallback-render smoke test.
 *
 * Renders every console page with the backend unreachable (the initial render
 * performs no effects, so each hook returns its "no data" state) and asserts
 * that the original hard-coded values still appear. This is what guarantees the
 * wiring did not change what the UI shows when the API is down.
 */
import { renderToString } from "react-dom/server";
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { build } from "esbuild";

const PAGES = [
  "Overview",
  "Live Map",
  "Incidents",
  "Resources",
  "Routes",
  "Teams",
  "Prediction Engine",
  "Resource Commander",
  "AI Assistant",
];

const EXPECT = {
  Overview: [
    "Situation overview",
    "Active incidents",
    "Prediction confidence",
    "People at risk",
    "Units deployed",
    "Priority alert",
    "Flash flood risk",
    "42 min",
    "3,200",
    "94% confidence",
    "3 evidence streams",
    "Next best actions",
    "Pre-position 2 rescue teams near Ellis Bridge",
    "Operational capacity",
    "Rescue teams",
    "18",
    "24",
    "Ambulances",
    "Food kits",
    "Water units",
    "Incident feed",
    "Road blockage detected",
    "Route intelligence",
    "North rescue corridor",
    "CLEAR",
    "BLOCKED",
  ],
  "Live Map": [
    "Live operational map",
    "Sabarmati river belt",
    "Risk",
    "ETA",
    "People",
    "Confidence",
    "HIGH",
    "Open response plan",
  ],
  Incidents: [
    "Incident command queue",
    "Flash flood risk",
    "Sabarmati river belt",
    "AI assessment",
    "Create response workflow",
  ],
  Resources: [
    "Resource command",
    "Rescue teams",
    "Ambulances",
    "Food kits",
    "Water units",
    "Allocation queue",
    "2 rescue teams",
    "Stock health",
    "Water",
    "Reserve 180 units",
  ],
  Routes: [
    "Route intelligence",
    "Mission routing",
    "North rescue corridor",
    "Ashram Road",
    "Relief camp supply route",
    "Share recommended route",
  ],
  Teams: [
    "Field teams",
    "Rescue Team 04",
    "Medical Unit 07",
    "NGO Relief 12",
    "Rescue Team 09",
    "Available teams",
    "Deployed",
    "Standby",
    "Comms health",
  ],
  "Prediction Engine": [
    "Prediction engine",
    "Flash flood propagation",
    "HIGH RISK",
    "Forecast timeline",
    "Why the model believes this",
    "River sensor trend",
    "View model decision trail",
  ],
  "Resource Commander": [
    "Resource Commander",
    "Allocation plan",
    "Deploy 2 rescue teams to Ellis Bridge",
    "Constraint monitor",
    "Ambulance availability",
    "Rescue team coverage",
    "Water reserve",
    "Fuel stock",
    "Operator attention",
  ],
  "AI Assistant": [
    "Ask AegisAI",
    "Operational conversation",
    "I’m monitoring the active Ahmedabad incident",
    "What should Command focus on right now?",
    "Suggested prompts",
    "Summarize the current situation",
    "Trust layer",
    "Human confirmation required",
  ],
};

const SRC = "src/App.tsx";
const GENERATED_PAGE = "src/__smoke_page.tsx";
const GENERATED_ENTRY = "src/__smoke_entry.tsx";
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
      outfile: "smoke/.page.cjs",
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
    html = execFileSync(process.execPath, ["smoke/.page.cjs"], {
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
  if (missing.length === 0) {
    console.log(`PASS  ${page.padEnd(19)} (${html.length} bytes, ${EXPECT[page].length} probes)`);
  } else {
    failures++;
    console.log(`FAIL  ${page.padEnd(19)} missing: ${JSON.stringify(missing)}`);
  }
}

for (const file of [GENERATED_PAGE, GENERATED_ENTRY]) {
  try {
    unlinkSync(file);
  } catch {}
}

console.log(
  failures === 0
    ? `\nALL ${PAGES.length} PAGES RENDER WITH FALLBACK DATA`
    : `\n${failures} PAGE(S) FAILED`,
);
process.exit(failures === 0 ? 0 : 1);
