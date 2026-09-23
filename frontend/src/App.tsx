import React from "react";
import { Routes, Route } from "react-router-dom";
import { DashboardLayout } from "./pages/DashboardLayout";
import { CommandCenter } from "./pages/CommandCenter";
import { IncidentDetail } from "./pages/IncidentDetail";

export const App: React.FC = () => {
  return (
    <Routes>
      <Route path="/" element={<DashboardLayout />} />
      <Route path="/dashboard/:zoneId?" element={<DashboardLayout />} />
      <Route path="/command-center" element={<CommandCenter />} />
      <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
    </Routes>
  );
};