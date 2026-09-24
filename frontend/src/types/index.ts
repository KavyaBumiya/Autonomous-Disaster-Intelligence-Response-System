export interface Zone {
  zone_id: string;
  name: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_meters: number;
  priority_score?: number;
  victim_count?: number;
  disaster_type?: string;
}

export interface Incident {
  incident_id: string;
  zone_id: string;
  disaster_type: string;
  severity_score: number;
  priority_score: number;
  confidence: number;
  xai_reasoning: string;
  status: string;
  report_count: number;
  avg_trust_score: number;
  victim_count: number;
  victim_confidence: number;
  lat: number;
  lng: number;
  created_at: string;
}

export interface Report {
  report_id: string;
  zone_id: string;
  source: string;
  trust_score: number;
  suppressed: boolean;
  disaster_type: string;
  lat: number;
  lng: number;
  message_text?: string;
  transcript?: string;
  summary: string;
  created_at: string;
}

export interface Resource {
  resource_id: string;
  name: string;
  resource_type: string;
  capacity: number;
  current_load: number;
  available: boolean;
  lat: number;
  lng: number;
  assigned_zone_id?: string;
}

export interface Action {
  action_id: string;
  incident_id: string;
  zone_id: string;
  action_type: string;
  description: string;
  status: string;
  priority_score: number;
  approved_by?: string;
  created_at: string;
}

export interface WebSocketEvent {
  event: string;
  payload: unknown;
  timestamp: string;
  source: string;
}

export interface PredictionResult {
  affected_cells?: Array<{ lat: number; lng: number; intensity: number; time_step: number }>;
  burned_area?: Array<{ lat: number; lng: number; intensity: number; time_step: number }>;
  max_intensity: number;
  flooded_percentage?: number;
  burned_area_percentage?: number;
  spread_direction_degrees?: number;
  expires_at: string;
  priority_delta?: number;
  new_priority?: number;
}