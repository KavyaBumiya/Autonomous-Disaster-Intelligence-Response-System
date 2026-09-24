import React, { Suspense, lazy } from "react";
import { Routes, Route } from "react-router-dom";

const DashboardLayout = lazy(() =>
  import("./pages/DashboardLayout").then((m) => ({ default: m.DashboardLayout }))
);
const CommandCenter = lazy(() =>
  import("./pages/CommandCenter").then((m) => ({ default: m.CommandCenter }))
);
const IncidentDetail = lazy(() =>
  import("./pages/IncidentDetail").then((m) => ({ default: m.IncidentDetail }))
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
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={<DashboardLayout />} />
        <Route path="/dashboard/:zoneId?" element={<DashboardLayout />} />
        <Route path="/command-center" element={<CommandCenter />} />
        <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
      </Routes>
    </Suspense>
  );
};
