import React from "react";

import { ResourcePanel as LiveResourcePanel } from "@/pages/ResourceStatusPanel";

interface ResourcePanelProps {
  zoneId?: string | null;
  incidentId?: string | null;
}

/** Thin wrapper so pages that import the components/ path get the live API panel. */
export const ResourcePanel: React.FC<ResourcePanelProps> = ({
  zoneId,
  incidentId,
}) => <LiveResourcePanel zoneId={zoneId} incidentId={incidentId} />;
