export interface GlobeZone {
  zone_id: string;
  name: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_meters: number;
  priority_score: number;
  victim_count: number;
}

export interface GlobeIncident {
  incident_id: string;
  zone_id?: string | null;
  disaster_type?: string | null;
  lat?: number | null;
  lng?: number | null;
  priority_score?: number | null;
  severity_score?: number | null;
  status?: string | null;
}

export interface GlobeResource {
  resource_id: string;
  name?: string | null;
  resource_type?: string | null;
  lat?: number | null;
  lng?: number | null;
  available?: boolean | null;
  current_load?: number | null;
  capacity?: number | null;
}

export interface GlobeEarthquake {
  id?: string;
  usgs_id?: string;
  magnitude: number;
  lat: number;
  lng: number;
  depth_km?: number | null;
  risk_score?: number | null;
}

export interface GlobeFire {
  latitude: number;
  longitude: number;
  brightness?: number | null;
  confidence?: string | null;
  frp?: number | null;
}

export interface GlobeReport {
  report_id?: string;
  id?: string;
  lat?: number | null;
  lng?: number | null;
  disaster_type?: string | null;
  trust_score?: number | null;
}

export type LayerKey =
  | "zones"
  | "incidents"
  | "resources"
  | "earthquakes"
  | "fires"
  | "reports";

export interface MapLayers {
  zones: GlobeZone[];
  incidents: GlobeIncident[];
  resources: GlobeResource[];
  earthquakes: GlobeEarthquake[];
  fires: GlobeFire[];
  reports: GlobeReport[];
}

export const EMPTY_LAYERS: MapLayers = {
  zones: [],
  incidents: [],
  resources: [],
  earthquakes: [],
  fires: [],
  reports: [],
};

export const LAYER_ORDER: LayerKey[] = [
  "zones",
  "incidents",
  "resources",
  "reports",
  "earthquakes",
  "fires",
];

export const LAYER_LABELS: Record<LayerKey, string> = {
  zones: "Priority zones",
  incidents: "Incidents",
  resources: "Resources",
  reports: "Citizen reports",
  earthquakes: "Seismic",
  fires: "Active fires",
};
