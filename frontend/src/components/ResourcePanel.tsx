import React from "react";

interface ResourcePanelProps {
  zoneId?: string | null;
  incidentId?: string | null;
}

export const ResourcePanel: React.FC<ResourcePanelProps> = ({
  zoneId,
  incidentId,
}) => {
  return (
    <div className="p-4 bg-gray-800/50 rounded-lg">
      <h3 className="font-medium text-white mb-3">
        Resource Commander
      </h3>

      <p className="text-sm text-gray-400">
        Zone: {zoneId || "None"}
      </p>

      <p className="text-sm text-gray-400">
        Incident: {incidentId || "None"}
      </p>
    </div>
  );
};