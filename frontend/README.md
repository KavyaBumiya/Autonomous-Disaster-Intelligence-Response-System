# AegisAI — Frontend Command Center

React + TypeScript + Vite operator console for AegisAI, wired to the FastAPI +
Socket.IO backend.

## Pages

### Operations
- **Overview** — situation overview, live map, critical alert, AI recommendations, resources, incident feed, route intelligence.
- **Live Map** — full map workspace with Risk / Routes / Teams / Shelters layers and map controls.
- **Incidents** — searchable incident command queue with selected-incident detail and response workflow.
- **Resources** — resource capacity, allocation queue, stock health and allocation actions.
- **Routes** — route intelligence, map, mission routing controls and route-sharing workflow.
- **Teams** — field-team roster, specialty, deployment state, ETA and readiness.

### AI systems
- **Prediction Engine** — active forecast, confidence, impact window, timeline and model evidence.
- **Resource Commander** — concrete resource allocations, confidence, constraints and operator review.
- **AI Assistant** — contextual conversational command interface with suggested prompts and trust layer.

## Run

```bash
npm install
npm run dev          # http://localhost:5173
```

With `VITE_API_BASE_URL` empty, the dev server proxies `/api` and `/socket.io`
to `VITE_DEV_PROXY_TARGET` (default `http://localhost:8000`), so the console runs
same-origin locally and needs no CORS configuration.

## Verify

```bash
npm run verify       # typecheck + fallback render test + production build
```

- `npm run typecheck` — `tsc` over the whole tree.
- `npm run smoke` — server-renders all nine pages with the backend unreachable
  and asserts the original values are still on screen. This is the guard against
  silently changing what the console shows when the API is down.
- `npm run build` — production bundle.

## Backend integration

Data lives in `src/lib/`, not in the components:

| File | Responsibility |
| --- | --- |
| `config.ts` | Env-driven API/socket origin, poll interval, timeouts. |
| `api.ts` | Typed REST client for the endpoints below. |
| `types.ts` | Response interfaces, checked against the FastAPI handlers. |
| `mappers.ts` | Backend payloads → the view models the UI already renders. |
| `fallbacks.ts` | The console's original hard-coded values, used when data is absent. |
| `hooks.ts` | Polling reads; the source of truth. |
| `socket.ts` | Socket.IO feed; only triggers an early refresh. |
| `consoleData.tsx` | Context that assembles and publishes the above. |
| `useAssistant.ts` | `POST /api/command/query` conversation with a stable id. |

Endpoints consumed: `/api/health`, `/api/command/health`, `/api/zones`,
`/api/incidents`, `/api/resources`, `/api/predictions/{zone_id}`,
`/api/routes/compute`, `/api/command/approval-queue`, `/api/command/query`,
`/api/command/resources/available`, `PATCH /api/actions/{action_id}`,
`POST /api/resources/{incident_id}/assign-resources`.

### Design rules

- **The UI owns the design, the provider owns the data.** Card labels, icons and
  evidence category names are declared in `App.tsx` and passed to the provider as
  `VISUALS`, so data wiring never moves a label or restyles a component.
- **Polling is the source of truth; the socket is an optimisation.** If
  Socket.IO is unavailable the console keeps working, and reconnection is
  bounded so a missing backend cannot flood the console with errors.
- **Every panel has a fallback.** "No data" and "no backend" are different
  states: the first renders an empty shell, the second renders the original
  demo values.
- **Actions stay human-gated.** Allocation and approval buttons call the
  backend's commander endpoints, which only *draft* work for review; nothing
  dispatches autonomously.

## Deployment

The console and the API deploy independently. Copy `.env.example` and set:

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Absolute API origin, e.g. `https://api.example.com`. Empty = same origin. |
| `VITE_SOCKET_URL` | Absolute Socket.IO origin. Defaults to the API origin. |
| `VITE_POLL_INTERVAL_MS` | Per-panel re-read cadence. Default `15000`. |
| `VITE_REQUEST_TIMEOUT_MS` | REST read timeout. Default `20000`. |
| `VITE_COMMAND_TIMEOUT_MS` | AI call timeout. Default `90000`. |
| `VITE_ZONE_ID` | Pin the console to one zone. Empty = highest-priority zone. |

Because the build embeds these values, set them before `npm run build`.

On the API side, set `FRONTEND_ORIGIN` to the console's deployed origin(s),
comma-separated. That locks both REST CORS and the Socket.IO handshake to your
own frontend; leaving it empty keeps the permissive local-demo default.

## AegisAI production backend

The frontend now defaults to the deployed AegisAI API when `VITE_API_BASE_URL` is not provided:

`https://autonomous-disaster-intelligence.onrender.com`

For a Vercel deployment, set:

- `VITE_API_BASE_URL=https://autonomous-disaster-intelligence.onrender.com`
- `VITE_SOCKET_URL=https://autonomous-disaster-intelligence.onrender.com`
- `VITE_MAPBOX_TOKEN=<your public Mapbox token>`

The backend integration is unauthenticated and exposes REST under `/api`; Socket.IO uses the same production origin.
