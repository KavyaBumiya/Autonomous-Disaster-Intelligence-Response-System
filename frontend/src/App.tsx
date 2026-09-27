import React, { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";

const DashboardLayout = lazy(() =>
  import("./pages/DashboardLayout").then((m) => ({ default: m.DashboardLayout }))
);
const CommandCenter = lazy(() =>
  import("./pages/CommandCenter").then((m) => ({ default: m.CommandCenter }))
);
const IncidentDetail = lazy(() =>
  import("./pages/IncidentDetail").then((m) => ({ default: m.IncidentDetail }))
);
const ResourcesPage = lazy(() =>
  import("./pages/ResourcesPage").then((m) => ({ default: m.ResourcesPage }))
);
const PredictionsPage = lazy(() =>
  import("./pages/PredictionsPage").then((m) => ({ default: m.PredictionsPage }))
);
const HeatmapsPage = lazy(() =>
  import("./pages/HeatmapsPage").then((m) => ({ default: m.HeatmapsPage }))
);
const AlertsPage = lazy(() =>
  import("./pages/AlertsPage").then((m) => ({ default: m.AlertsPage }))
);
const Zone3DPage = lazy(() =>
  import("./pages/Zone3DPage").then((m) => ({ default: m.Zone3DPage }))
);

const RouteFallback = () => (
  <div className="ops-shell flex min-h-screen items-center justify-center text-white">
    <div className="ops-panel px-6 py-5 text-center">
      <div className="ops-kicker mb-2">Loading</div>
      <div className="ops-title">Preparing operational view…</div>
    </div>
  </div>
);

export const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<DashboardLayout />} />
          <Route path="/dashboard" element={<DashboardLayout />} />
          <Route path="/dashboard/:zoneId" element={<DashboardLayout />} />

          <Route path="/command" element={<CommandCenter />} />
          <Route path="/command-center" element={<CommandCenter />} />

          <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
          <Route path="/resources" element={<ResourcesPage />} />
          <Route path="/predictions" element={<PredictionsPage />} />
          <Route path="/heatmaps" element={<HeatmapsPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/3d/:zoneId" element={<Zone3DPage />} />

          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
};
