import React, { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  resourcesApi,
  incidentsApi,
  apiErrorMessage,
  type Resource,
} from "@/services/api";
import { Button, EmptyState, ErrorState, LoadingState, Modal, ResourceStatusBadge } from "@/components/ui";

interface ResourcePanelProps {
  zoneId?: string | null;
  incidentId?: string | null;
  compact?: boolean;
  showShelterView?: boolean;
}

type FilterKey = "all" | "available" | "assigned";

const TYPE_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All types" },
  { value: "medical", label: "Medical" },
  { value: "fire", label: "Fire" },
  { value: "rescue", label: "Rescue" },
  { value: "police", label: "Police" },
  { value: "shelter", label: "Shelter" },
  { value: "transport", label: "Transport" },
];

const ResourceCard: React.FC<{
  resource: Resource;
  onAssign: (id: string) => void;
  onRelease: (id: string) => void;
  busy: boolean;
}> = ({ resource, onAssign, onRelease, busy }) => {
  const isAvail =
    resource.available === true &&
    (resource.current_load ?? 0) < (resource.capacity ?? 0);

  return (
    <div className="ops-resource-card">
      <div className="flex items-start justify-between gap-2">
        <div className="ops-resource-title" title={resource.name || "Unnamed resource"}>
          {resource.name || "Unnamed resource"}
        </div>
        <ResourceStatusBadge
          available={resource.available}
          currentLoad={resource.current_load}
          capacity={resource.capacity}
        />
      </div>
      <div className="ops-resource-meta mt-1">{resource.resource_type || "Unknown type"}</div>
      <div className="ops-resource-meta mt-2 ops-mono">
        Load {resource.current_load ?? 0}/{resource.capacity ?? 0}
        {resource.assigned_zone_id
          ? ` · zone ${resource.assigned_zone_id.slice(0, 8)}`
          : ""}
      </div>
      <div className="ops-resource-action">
        {isAvail ? (
          <Button
            variant="primary"
            size="sm"
            block
            disabled={busy}
            onClick={() => onAssign(resource.resource_id)}
          >
            Assign
          </Button>
        ) : (
          <Button
            size="sm"
            block
            disabled={busy}
            onClick={() => onRelease(resource.resource_id)}
          >
            Release
          </Button>
        )}
      </div>
    </div>
  );
};

export const ResourcePanel: React.FC<ResourcePanelProps> = ({
  zoneId,
  incidentId,
  compact = false,
}) => {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<FilterKey>("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [pendingResource, setPendingResource] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const {
    data: resources = [],
    isLoading,
    isError,
    refetch,
  } = useQuery<Resource[]>({
    queryKey: ["resources", zoneId],
    queryFn: async () => {
      const response = await resourcesApi.list(
        zoneId ? { zone_id: zoneId } : {},
      );
      return response.data.resources || [];
    },
  });

  const availableResources = resources.filter(
    (resource) =>
      resource.available === true &&
      (resource.current_load ?? 0) < (resource.capacity ?? 0),
  );

  const assignedResources = resources.filter(
    (resource) =>
      resource.available !== true ||
      (resource.assigned_zone_id ?? null) !== null,
  );

  const filtered = useMemo(() => {
    let list =
      statusFilter === "available"
        ? availableResources
        : statusFilter === "assigned"
          ? assignedResources
          : resources;
    if (typeFilter !== "all") {
      list = list.filter(
        (r) => (r.resource_type || "").toLowerCase() === typeFilter,
      );
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (r) =>
          (r.name || "").toLowerCase().includes(q) ||
          (r.resource_type || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [resources, statusFilter, typeFilter, search, availableResources, assignedResources]);

  const openAssign = (resourceId: string) => {
    if (!zoneId && !incidentId) {
      toast.error("Select a zone or incident before assigning a resource.");
      return;
    }
    setPendingResource(resourceId);
    setAssignOpen(true);
  };

  const handleAssign = async () => {
    if (!pendingResource) return;
    setBusy(true);
    try {
      let targetIncidentId = incidentId;

      if (!targetIncidentId && zoneId) {
        const incRes = await incidentsApi.list({
          zone_id: zoneId,
          active_only: true,
          limit: 1,
        });
        targetIncidentId = incRes.data.incidents?.[0]?.incident_id ?? null;
      }

      if (!targetIncidentId) {
        toast.error("No active incident found for this zone.");
        setAssignOpen(false);
        return;
      }

      const response = await resourcesApi.assign(targetIncidentId);
      toast.success(response.data?.message || "Resource allocation complete");

      await queryClient.invalidateQueries({ queryKey: ["resources"] });
      await queryClient.invalidateQueries({ queryKey: ["incidents"] });
      setAssignOpen(false);
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error) || "Failed to assign resource");
    } finally {
      setBusy(false);
      setPendingResource(null);
    }
  };

  const handleRelease = async (resourceId: string) => {
    setBusy(true);
    try {
      const response = await resourcesApi.update(resourceId, {
        available: true,
        current_load: 0,
      });
      toast.success(response.data?.message || "Resource released successfully");
      await queryClient.invalidateQueries({ queryKey: ["resources"] });
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error) || "Failed to release resource");
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) {
    return (
      <div className="ops-panel">
        <div className="ops-panel-header">
          <div>
            <div className="ops-kicker">Resources</div>
            <div className="ops-title">Resource commander</div>
          </div>
        </div>
        <LoadingState label="Loading resources…" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="ops-panel">
        <div className="ops-panel-header">
          <div>
            <div className="ops-kicker">Resources</div>
            <div className="ops-title">Resource commander</div>
          </div>
        </div>
        <ErrorState message="Unable to load resources from the backend." onRetry={() => void refetch()} />
      </div>
    );
  }

  const filters = (
    <div className="flex flex-wrap items-center gap-2 px-4 py-3">
      <input
        className="ops-input"
        style={{ maxWidth: 200 }}
        placeholder="Search resources…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Search resources"
      />
      <select
        className="ops-select"
        style={{ width: "auto" }}
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value as FilterKey)}
        aria-label="Filter by status"
      >
        <option value="all">All statuses</option>
        <option value="available">Available</option>
        <option value="assigned">Assigned</option>
      </select>
      <select
        className="ops-select"
        style={{ width: "auto" }}
        value={typeFilter}
        onChange={(e) => setTypeFilter(e.target.value)}
        aria-label="Filter by type"
      >
        {TYPE_FILTERS.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>
      <span className="ops-mono ml-auto text-xs text-slate-500">
        {filtered.length}/{resources.length}
      </span>
    </div>
  );

  if (compact) {
    const list = filtered.slice(0, 6);
    return (
      <div className="ops-panel">
        <div className="ops-panel-header">
          <div>
            <div className="ops-kicker">Resources</div>
            <div className="ops-title">Resource commander</div>
          </div>
          <span className="ops-mono text-xs text-slate-400">
            {availableResources.length} ready
          </span>
        </div>
        <div className="ops-scroll-y ops-resource-grid" style={{ maxHeight: 420, padding: 14, gridTemplateColumns: "1fr" }}>
          {list.length === 0 ? (
            <EmptyState title="No resources" message="No resources match the current filters." />
          ) : (
            list.map((r) => (
              <ResourceCard
                key={r.resource_id}
                resource={r}
                onAssign={openAssign}
                onRelease={handleRelease}
                busy={busy}
              />
            ))
          )}
        </div>
        <div className="px-4 pb-4">
          <Button block onClick={() => setStatusFilter(statusFilter === "available" ? "all" : "available")}>
            {statusFilter === "available" ? "Show all" : "Show available only"}
          </Button>
        </div>
        <Modal
          open={assignOpen}
          onClose={() => setAssignOpen(false)}
          title="Confirm assignment"
          footer={
            <>
              <Button onClick={() => setAssignOpen(false)} disabled={busy}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleAssign} disabled={busy}>
                {busy ? "Assigning…" : "Assign resource"}
              </Button>
            </>
          }
        >
          <p className="text-sm leading-6 text-slate-300">
            This will run the backend resource-commander allocation for the active incident in
            the selected zone. The action is logged for audit.
          </p>
        </Modal>
      </div>
    );
  }

  return (
    <div className="ops-panel">
      <div className="ops-panel-header">
        <div>
          <div className="ops-kicker">Resources</div>
          <div className="ops-title">Resource commander</div>
        </div>
        <div className="flex gap-2">
          <span className="ops-badge ops-badge-cyan">
            <span className="ops-badge-dot" /> {availableResources.length} ready
          </span>
          <span className="ops-badge ops-badge-amber">
            <span className="ops-badge-dot" /> {assignedResources.length} assigned
          </span>
        </div>
      </div>

      {filters}

      <div className="ops-resource-grid px-4 pb-4">
        {filtered.length === 0 ? (
          <div style={{ gridColumn: "1 / -1" }}>
            <EmptyState
              title="No matching resources"
              message="Adjust the status, type, or search filters to see more units."
              action={
                <Button
                  size="sm"
                  onClick={() => {
                    setStatusFilter("all");
                    setTypeFilter("all");
                    setSearch("");
                  }}
                >
                  Reset filters
                </Button>
              }
            />
          </div>
        ) : (
          filtered.map((r) => (
            <ResourceCard
              key={r.resource_id}
              resource={r}
              onAssign={openAssign}
              onRelease={handleRelease}
              busy={busy}
            />
          ))
        )}
      </div>

      <Modal
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        title="Confirm assignment"
        footer={
          <>
            <Button onClick={() => setAssignOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleAssign} disabled={busy}>
              {busy ? "Assigning…" : "Assign resource"}
            </Button>
          </>
        }
      >
        <p className="text-sm leading-6 text-slate-300">
          This will run the backend resource-commander allocation for the active incident in
          the selected zone. The action is logged for audit.
        </p>
      </Modal>
    </div>
  );
};
