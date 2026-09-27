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

/**
 * One projected cell from GET /api/predictions/{zone_id}.
 *
 * The engine emits POINTS on a grid, not polygons, so the globe renders each
 * cell as its own intensity-scaled entity rather than an outline.
 */
export interface GlobePredictionCell {
  zone_id: string;
  disaster_type: "flood" | "fire";
  lat: number;
  lng: number;
  intensity: number;
  time_step: number;
}

/** Per-zone row from GET /api/heatmaps/victim-density. */
export interface GlobeVictimCell {
  zone_id: string;
  zone_name?: string | null;
  lat: number;
  lng: number;
  victim_count: number;
  victim_density: number;
  area_km2?: number | null;
}

/**
 * POST /api/routes/compute.
 *
 * NOTE: `geometry` is a plain array of [lng, lat] pairs, NOT a GeoJSON
 * LineString. The previous type claimed GeoJSON and every consumer had to
 * special-case it.
 */
export interface GlobeRoute {
  zone_id: string;
  zone_name?: string | null;
  disaster_type: string;
  geometry: [number, number][];
  distance_km: number;
  estimated_minutes: number;
  source?: string | null;
  engine?: string | null;
  blocked_roads: string[];
}

/** Resource subtype "shelter", projected from the already-loaded resources. */
export interface GlobeShelter {
  resource_id: string;
  name?: string | null;
  lat: number;
  lng: number;
  capacity: number;
  current_load: number;
  available: boolean;
}

/** GET /api/weather/current sampled at one zone centroid. */
export interface GlobeWeather {
  lat: number;
  lng: number;
  zone_id: string | null;
  risk_score: number;
  rainfall_mm_hr: number;
  wind_speed_kmh: number;
  temperature_c: number | null;
  weather_main: string;
  provider: string;
  from_cache: boolean;
}

/**
 * XAI overlay. Derived entirely from the `xai_reasoning` text that
 * GET /api/incidents already returns, so this layer costs zero extra requests
 * and cannot trigger the per-incident LLM calls of /api/command/explain.
 */
export interface GlobeXaiFactor {
  incident_id: string;
  lat: number;
  lng: number;
  priority_score: number;
  priority_band?: string | null;
  /** Factor name with the largest point contribution, e.g. "Victim Severity". */
  top_factor: string;
  top_factor_points: number;
  top_factor_weight_pct: number;
}

export type LayerKey =
  | "zones"
  | "incidents"
  | "predictions"
  | "victims"
  | "resources"
  | "shelters"
  | "routes"
  | "reports"
  | "earthquakes"
  | "fires"
  | "weather"
  | "xai";

export interface MapLayers {
  zones: GlobeZone[];
  incidents: GlobeIncident[];
  predictions: GlobePredictionCell[];
  victims: GlobeVictimCell[];
  resources: GlobeResource[];
  shelters: GlobeShelter[];
  routes: GlobeRoute[];
  earthquakes: GlobeEarthquake[];
  fires: GlobeFire[];
  reports: GlobeReport[];
  weather: GlobeWeather[];
  xai: GlobeXaiFactor[];
}

export const EMPTY_LAYERS: MapLayers = {
  zones: [],
  incidents: [],
  predictions: [],
  victims: [],
  resources: [],
  shelters: [],
  routes: [],
  earthquakes: [],
  fires: [],
  reports: [],
  weather: [],
  xai: [],
};

export const LAYER_ORDER: LayerKey[] = [
  "zones",
  "incidents",
  "predictions",
  "victims",
  "resources",
  "shelters",
  "routes",
  "reports",
  "earthquakes",
  "fires",
  "weather",
  "xai",
];

export const LAYER_LABELS: Record<LayerKey, string> = {
  zones: "Priority zones",
  incidents: "Incidents",
  predictions: "Model projection",
  victims: "Victim density",
  resources: "Resources",
  shelters: "Shelters",
  routes: "Evacuation routes",
  reports: "Citizen reports",
  earthquakes: "Seismic",
  fires: "Active fires",
  weather: "Weather",
  xai: "XAI top factor",
};

/**
 * Layers whose data costs a request per zone, so the page only fetches them
 * while the operator has them switched on.
 */
export const PER_ZONE_LAYER_KEYS: LayerKey[] = [
  "predictions",
  "routes",
  "weather",
];

/** Max zones sampled for the per-zone layers, to bound fan-out. */
export const PER_ZONE_LAYER_LIMIT = 24;
