import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { WhatIfSimulation } from "../components/WhatIfSimulation";
import { RouteIntelligence } from "../components/RouteIntelligence";
import { ResourcePanel } from "../components/ResourcePanel";

interface IncidentDetailProps {}

interface Incident {
  disaster_type?: string;
  zone_id?: string;
  priority_score?: number;
  status?: string;
  xai_reasoning?: string;
  victim_count?: number;
  victim_confidence?: number;
  report_count?: number;
}

export const IncidentDetail: React.FC<IncidentDetailProps> = () => {
  const { incidentId } = useParams<{ incidentId: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  const { data, isLoading } = useQuery<Incident>({
    queryKey: ["incident", incidentId],
    queryFn: async () => {
      const res = await axios.get(`/api/incidents/${incidentId}`);
      return res.data;
    },
    enabled: !!incidentId,
  });

  useEffect(() => {
    if (data) {
      setIncident(data);
      setLoading(false);
    }
  }, [data]);

  if (loading || !incident) {
    return (
      <div className="card p-6 max-w-md mx-auto">
        <p>Loading incident details...</p>
      </div>
    );
  }

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      {/* Main Incident Details */}
      <div className="lg:col-span-2 card p-6">
        <h1 className="text-2xl font-bold mb-4">
          {incident.disaster_type?.toUpperCase() || "Incident"}
        </h1>

        <p className="text-lg text-gray-300 mb-3">
          Zone: {incident.zone_id || "N/A"}
        </p>

        {/* Priority & Status */}
        <div className="mb-4 p-4 bg-gray-800/50 rounded-lg">
          <p className="font-medium text-white mb-2">Priority Score:</p>
          <p className="text-3xl font-bold text-yellow-400">
            {incident.priority_score || 0}/100
          </p>
          {incident.status && (
            <p className="mt-2 text-sm">
              {incident.status}
            </p>
          )}
        </div>

        {/* XAI Reasoning */}
        <div className="mb-4 p-4 bg-gray-800/50 rounded-lg h-48 overflow-y-auto">
          <p className="font-medium text-white mb-2">XAI Reasoning:</p>
          <p className="text-sm text-gray-300 whitespace-pre-wrap">
            {incident.xai_reasoning || "No reasoning available"}
          </p>
        </div>

        {/* Victim Data */}
        <div className="mb-4 p-4 bg-gray-800/50 rounded-lg">
          <p className="font-medium text-white mb-2">Victims:</p>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-gray-400">Count:</span>
              <span className="font-bold text-white">
                {incident.victim_count || 0}
              </span>
            </div>
            <div>
              <span className="text-gray-400">Confidence:</span>
              <span className="font-bold text-yellow-400">
                {(incident.victim_confidence || 0).toFixed(2)}
              </span>
            </div>
          </div>
        </div>

        {/* Reports count */}
        <div>
          <p className="text-sm text-gray-300 mb-2">Reports:</p>
          <p className="text-lg font-bold">{incident.report_count || 0}</p>
        </div>

        {/* Tabs Navigation */}
        <div className="mt-4 pt-4 border-t border-gray-700">
          <h4 className="text-sm text-gray-300 mb-3">Navigation</h4>
          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={() => setActiveTab("overview")}
              className={activeTab === "overview" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
            >
              Overview
            </button>
            <button
              onClick={() => setActiveTab("prediction")}
              className={activeTab === "prediction" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
            >
              Prediction
            </button>
            <button
              onClick={() => setActiveTab("resources")}
              className={activeTab === "resources" ? "bg-blue-600 text-white rounded-lg py-1 px-2 text-xs font-medium" : "bg-gray-700 text-gray-300 rounded-lg py-1 px-2 text-xs font-medium"}
            >
              Resources
            </button>
          </div>
        </div>
      </div>

      {/* Prediction Tab */}
      {activeTab === "prediction" && incidentId && (
        <div className="bg-gray-800/50 p-4 rounded-lg h-fit">
          <WhatIfSimulation
            zoneId={incident.zone_id || ""}
            incidentId={incidentId}
            disasterType={incident.disaster_type || "flood"}
          />
        </div>
      )}

      {/* Route Intelligence Tab */}
      {activeTab === "route" && incidentId && (
        <div className="bg-gray-800/50 p-4 rounded-lg h-fit">
          <RouteIntelligence zoneId={incident.zone_id || ""} incidentId={incidentId} />
        </div>
      )}

      {/* Resources Tab */}
      {activeTab === "resources" && incidentId && (
        <div className="bg-gray-800/50 p-4 rounded-lg h-fit">
          <ResourcePanel zoneId={incident.zone_id || ""} incidentId={incidentId} />
        </div>
      )}
    </div>
  );
};

