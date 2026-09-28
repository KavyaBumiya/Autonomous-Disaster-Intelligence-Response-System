# AegisAI page modules

Each command-center page is isolated into its own module. `App.tsx` owns only the
application shell, navigation state, shared role state, and page selection.

- `Overview.tsx`
- `LiveMap.tsx`
- `Incidents.tsx`
- `Resources.tsx`
- `RoutesPage.tsx`
- `TeamsPage.tsx`
- `PredictionPage.tsx`
- `CommanderPage.tsx`
- `AssistantPage.tsx`

`pages/index.ts` is the single barrel import used by `App.tsx`.

Shared presentation primitives live in `src/components/ui.tsx`, while backend
state and API access remain in `src/lib/*`.
