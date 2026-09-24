import React, { Suspense, lazy } from "react";
import { Link, useParams } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { Button, EmptyState, LoadingState } from "@/components/ui";

const CriticalZone3D = lazy(() =>
  import("./CriticalZone3D").then((m) => ({ default: m.CriticalZone3D }))
);

export const Zone3DPage: React.FC = () => {
  const { zoneId } = useParams<{ zoneId: string }>();

  return (
    <AppShell>
      <section className="fade-in mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="ops-kicker mb-2">Digital twin</div>
          <h1 className="text-3xl font-bold tracking-tight">3D zone view</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">
            Immersive terrain and structure view for the selected critical zone.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => window.history.back()}>Back</Button>
          <Link to="/dashboard" className="ops-button">
            Dashboard
          </Link>
        </div>
      </section>

      {!zoneId ? (
        <div className="ops-panel">
          <EmptyState
            title="No zone selected"
            message="Open this view from a zone on the dashboard or workspace."
            action={
              <Link to="/dashboard" className="ops-button ops-button-primary ops-button-sm">
                Go to dashboard
              </Link>
            }
          />
        </div>
      ) : (
        <div className="ops-panel overflow-hidden">
          <Suspense fallback={<LoadingState label="Loading 3D engine…" />}>
            <CriticalZone3D zoneId={zoneId} />
          </Suspense>
        </div>
      )}
    </AppShell>
  );
};
