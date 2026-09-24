import React from "react";
import { useQuery } from "@tanstack/react-query";

import { zonesApi, type Zone } from "@/services/api";
import { AppShell } from "@/components/AppShell";
import { ResourcePanel } from "./ResourceStatusPanel";
import { EmptyState, LoadingState } from "@/components/ui";

export const ResourcesPage: React.FC = () => {
  const { data: zoneResponse, isLoading } = useQuery<{ zones: Zone[] }>({
    queryKey: ["zones"],
    queryFn: async () => (await zonesApi.withPriority()).data,
    refetchInterval: 30000,
  });
  const zones = zoneResponse?.zones ?? [];

  return (
    <AppShell>
      <section className="fade-in mb-6">
        <div className="ops-kicker mb-2">Fleet</div>
        <h1 className="text-3xl font-bold tracking-tight">Resource commander</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          Search, filter, assign, and release response units across all operational zones.
        </p>
      </section>

      {isLoading ? (
        <div className="ops-panel">
          <LoadingState label="Loading zones…" />
        </div>
      ) : zones.length === 0 ? (
        <div className="ops-panel">
          <EmptyState title="No zones" message="Backend returned no zones to scope resources." />
        </div>
      ) : (
        <div className="space-y-5">
          {zones.slice(0, 6).map((zone) => (
            <div key={zone.zone_id}>
              <div className="mb-2 flex items-center justify-between">
                <div className="ops-kicker">
                  {zone.name || `Zone ${zone.zone_id.slice(0, 8)}`}
                </div>
                <span className="ops-mono text-xs text-slate-500">
                  priority {zone.priority_score ?? 0}/100
                </span>
              </div>
              <ResourcePanel zoneId={zone.zone_id} />
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
};
