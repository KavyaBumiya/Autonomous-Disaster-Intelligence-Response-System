import React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { Button, EmptyState } from "@/components/ui";
import { CesiumGlobe } from "@/components/CesiumGlobe";
import { zonesApi } from "@/services/api";

export const Zone3DPage: React.FC = () => {
  const { zoneId } = useParams<{ zoneId: string }>();
  const navigate = useNavigate();

  const zonesQuery = useQuery({
    queryKey: ["cesium-zones"],
    queryFn: () => zonesApi.list({ limit: 100 }).then((r) => r.data),
    staleTime: 60_000,
  });

  const handleSelectZone = (id: string) => {
    navigate(`/zones/${id}`);
  };

  return (
    <AppShell>
      <section className="fade-in mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="ops-kicker mb-2">Digital twin</div>
          <h1 className="text-3xl font-bold tracking-tight">3D disaster globe</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">
            Cesium Ion powered 3D terrain and zone visualization with real-time disaster data overlay.
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
          <CesiumGlobe
            zones={zonesQuery.data?.zones ?? []}
            onSelectZone={handleSelectZone}
          />
        </div>
      )}
    </AppShell>
  );
};
