import React from "react";
import { TopNav } from "./TopNav";

export const AppShell: React.FC<{
  isConnected?: boolean;
  alertCount?: number;
  children: React.ReactNode;
}> = ({ isConnected, alertCount = 0, children }) => (
  <div className="ops-shell text-white">
    <TopNav isConnected={isConnected} alertCount={alertCount} />
    <main className="ops-container py-6 md:py-8">{children}</main>
  </div>
);
