import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  resourcesApi,
  incidentsApi,
  apiErrorMessage,
  type Resource,
} from "@/services/api";

interface ResourcePanelProps {
  zoneId?: string | null;
  incidentId?: string | null;
  showShelterView?: boolean;
}

export const ResourcePanel: React.FC<ResourcePanelProps> = ({
  zoneId,
  incidentId,
}) => {
  const queryClient = useQueryClient();

  const {
    data: resources = [],
    isLoading,
    isError,
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
      (resource.current_load ?? 0) < (resource.capacity ?? 0)
  );

  const assignedResources = resources.filter(
    (resource) => resource.available !== true || (resource.assigned_zone_id ?? null) !== null
  );

  const handleAssign = async (resourceId: string) => {
    if (!zoneId && !incidentId) {
      toast.error("Select a zone or incident before assigning a resource.");
      return;
    }

    try {
      let targetIncidentId = incidentId;

      // Resolve a concrete incident for the zone if only a zone is selected
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
        return;
      }

      // Backend runs the resource-commander allocation for the incident
      const response = await resourcesApi.assign(targetIncidentId);
      toast.success(
        response.data?.message || "Resource allocation complete"
      );

      await queryClient.invalidateQueries({ queryKey: ["resources"] });
      await queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void resourceId;
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error) || "Failed to assign resource");
    }
  };

  const handleRelease = async (resourceId: string) => {
    try {
      const response = await resourcesApi.update(resourceId, {
        available: true,
        current_load: 0,
      });

      toast.success(
        response.data?.message || "Resource released successfully"
      );

      await queryClient.invalidateQueries({ queryKey: ["resources"] });
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error) || "Failed to release resource");
    }
  };

  if (isLoading) {
    return (
      <div className="p-4 bg-gray-800/50 rounded-lg h-fit">
        <h3 className="font-medium text-white mb-3">Resource Commander</h3>
        <p className="text-sm text-gray-400">Loading resources...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-4 bg-gray-800/50 rounded-lg h-fit">
        <h3 className="font-medium text-white mb-3">Resource Commander</h3>
        <p className="text-sm text-red-400">Unable to load resources.</p>
      </div>
    );
  }

  return (
    <div className="grid lg:grid-cols-2 gap-6">
      {/* Available Resources */}
      <div className="lg:col-span-1 bg-gray-800/50 p-4 rounded-lg h-fit">
        <h3 className="font-medium text-white mb-3">Available Resources</h3>

        {availableResources.length === 0 ? (
          <p className="text-sm text-gray-400">No available resources.</p>
        ) : (
          <div className="space-y-3">
            {availableResources.map((resource) => (
              <div
                key={resource.resource_id}
                className="p-3 bg-green-500/10 border-l-4 border-green-500 rounded"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">
                      {resource.name || "Unnamed resource"}
                    </p>
                    <p className="text-xs text-gray-400">
                      {resource.resource_type || "Unknown type"}
                    </p>
                    <p className="text-xs text-green-300 mt-1">
                      Load: {resource.current_load ?? 0}/{resource.capacity ?? 0}
                    </p>
                  </div>

                  <button
                    onClick={() => handleAssign(resource.resource_id)}
                    disabled={!zoneId && !incidentId}
                    className="bg-green-600 text-white text-xs rounded-lg py-2 px-3 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Assign
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Assigned Resources */}
      <div className="lg:col-span-1 bg-gray-800/50 p-4 rounded-lg h-fit">
        <h3 className="font-medium text-white mb-3">Assigned Resources</h3>

        {assignedResources.length === 0 ? (
          <p className="text-sm text-gray-400">No resources currently assigned.</p>
        ) : (
          <div className="space-y-3">
            {assignedResources.map((resource) => (
              <div
                key={resource.resource_id}
                className="p-3 bg-blue-500/10 border-l-4 border-blue-500 rounded"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">
                      {resource.name || "Unnamed resource"}
                    </p>
                    <p className="text-xs text-gray-400">
                      {resource.resource_type || "Unknown type"}
                    </p>
                    <p className="text-xs text-blue-300 mt-1">
                      Load: {resource.current_load ?? 0}/{resource.capacity ?? 0}
                      {resource.assigned_zone_id && ` · zone ${resource.assigned_zone_id.slice(0, 8)}`}
                    </p>
                  </div>

                  <button
                    onClick={() => handleRelease(resource.resource_id)}
                    className="bg-yellow-600 text-white text-xs rounded-lg py-2 px-3 hover:bg-yellow-500"
                  >
                    Release
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
