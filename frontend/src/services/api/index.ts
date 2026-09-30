/* eslint-disable @typescript-eslint/no-explicit-any */
import { CitySituationReport } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchCityReport(): Promise<CitySituationReport> {
  const response = await fetch(`${API_BASE}/api/city/report`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch city report: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTrafficReport(): Promise<any> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120_000); // 120 seconds
  try {
    const response = await fetch(`${API_BASE}/api/traffic/report`, {
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errJson = await response.json();
        if (errJson?.detail?.message) detail = errJson.detail.message;
        else if (errJson?.detail?.error) detail = errJson.detail.error;
        else if (errJson?.message) detail = errJson.message;
      } catch {}
      throw new Error(`Failed to fetch traffic report: ${detail}`);
    }
    return response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Traffic report request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function fetchFloodReport(): Promise<any> {
  const response = await fetch(`${API_BASE}/api/flood/report`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch flood report: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchWeatherKpi(): Promise<any> {
  const response = await fetch(`${API_BASE}/kpi/live/weather`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch weather KPI: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchPm25Kpi(): Promise<any> {
  const response = await fetch(`${API_BASE}/kpi/live/pm25`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch PM2.5 KPI: ${response.statusText}`);
  }
  return response.json();
}

export interface Pm25PredictionRegion {
  region: string;
  available: boolean;
  unavailable_reason: string | null;
  next_day_mean_ugm3: number | null;
  next_day_max_ugm3: number | null;
  model: string | null;
  is_ml_model: boolean;
  target_models: Record<string, string>;
  persistence_value_pm25_t0: number | null;
  fallback_reason: string | null;
}

export interface Pm25PredictionResponse {
  prediction_timestamp: string;
  prediction_horizon_hours: number;
  target_window: {
    start: string;
    end: string;
  };
  regions: Pm25PredictionRegion[];
  model_metadata: {
    run_id: string;
    selected_regions_ml: string[];
    selected_regions_persist: string[];
    selection_policy: string;
  };
  diagnostics: {
    predictions_total: number;
    predictions_ml: number;
    predictions_persist: number;
    regions_missing_features: string[];
    feature_report_rows: number;
  };
  source: string;
}

export async function fetchPm25Prediction(t0?: string): Promise<Pm25PredictionResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000); // 30 seconds
  const url = new URL(`${API_BASE}/api/pollution/predict`);
  if (t0) {
    url.searchParams.set('t0', t0);
  }
  try {
    const response = await fetch(url.toString(), {
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) {
      // Try to extract backend detail for a clearer error message
      let detail = response.statusText;
      try {
        const errJson = await response.json();
        if (errJson?.detail?.message) detail = errJson.detail.message;
        else if (errJson?.detail?.error) detail = errJson.detail.error;
        else if (errJson?.message) detail = errJson.message;
      } catch {}
      throw new Error(`Failed to fetch PM2.5 prediction: ${detail}`);
    }
    return response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('PM2.5 forecast request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export interface BusService {
  service_no: string;
  operator: string;
  direction: number;
  category: string;
  origin_code: string;
  destination_code: string;
  am_peak_freq: string | null;
  am_offpeak_freq: string | null;
  pm_peak_freq: string | null;
  pm_offpeak_freq: string | null;
  loop_desc: string | null;
}

export interface BusRoute {
  service_no: string;
  operator: string;
  direction: number;
  stop_sequence: number;
  bus_stop_code: string;
  distance: number | null;
  wd_first_bus: string | null;
  wd_last_bus: string | null;
  sat_first_bus: string | null;
  sat_last_bus: string | null;
  sun_first_bus: string | null;
  sun_last_bus: string | null;
}

export interface BusStop {
  bus_stop_code: string;
  road_name: string;
  description: string;
  latitude: number;
  longitude: number;
}

export interface TrainAlert {
  line: string;
  direction: string | null;
  station: string | null;
  message: string;
  status: string | null;
}

export interface TransitStatus {
  generated_at: string;
  bus_services_count: number;
  bus_routes_count: number;
  bus_stops_count: number;
  active_train_alerts: number;
  train_alerts: TrainAlert[];
  limitations: string[];
}

export async function fetchTransitStatus(limitAlerts = 20): Promise<TransitStatus> {
  const response = await fetch(`${API_BASE}/api/mobility/transit/status?limit_alerts=${limitAlerts}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch transit status: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchBusServices(limit = 1000, serviceNo?: string, operator?: string): Promise<BusService[]> {
  const url = new URL(`${API_BASE}/api/mobility/transit/bus-services`);
  url.searchParams.set('limit', limit.toString());
  if (serviceNo) url.searchParams.set('service_no', serviceNo);
  if (operator) url.searchParams.set('operator', operator);
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch bus services: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchBusRoutes(serviceNo: string, operator: string, direction: number): Promise<BusRoute[]> {
  const url = new URL(`${API_BASE}/api/mobility/transit/bus-routes`);
  url.searchParams.set('service_no', serviceNo);
  url.searchParams.set('operator', operator);
  url.searchParams.set('direction', direction.toString());
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch bus routes: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchBusStops(options?: { 
  busStopCode?: string; 
  lat?: number; 
  lon?: number; 
  radiusKm?: number; 
  limit?: number; 
  allStops?: boolean 
}): Promise<BusStop[]> {
  const url = new URL(`${API_BASE}/api/mobility/transit/bus-stops`);
  if (options?.busStopCode) {
    url.searchParams.set('bus_stop_code', options.busStopCode);
  } else if (options?.allStops) {
    url.searchParams.set('all_stops', 'true');
    if (options.limit) url.searchParams.set('limit', options.limit.toString());
  } else if (options?.lat !== undefined && options?.lon !== undefined) {
    url.searchParams.set('lat', options.lat.toString());
    url.searchParams.set('lon', options.lon.toString());
    url.searchParams.set('radius_km', (options.radiusKm || 1).toString());
    url.searchParams.set('limit', (options.limit || 200).toString());
  } else {
    throw new Error('Provide either bus_stop_code, all_stops=true, or lat/lon');
  }
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch bus stops: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTrainAlerts(line?: string, limit = 20): Promise<TrainAlert[]> {
  const url = new URL(`${API_BASE}/api/mobility/transit/train-alerts`);
  if (line) url.searchParams.set('line', line);
  url.searchParams.set('limit', limit.toString());
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch train alerts: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTransitStats(): Promise<any> {
  const response = await fetch(`${API_BASE}/api/mobility/transit/stats`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch transit stats: ${response.statusText}`);
  }
  return response.json();
}

// Roads API
export interface RoadWork {
  event_id: string;
  start_date: string;
  end_date: string;
  svc_dept: string;
  road_name: string;
  other: string;
  is_active: boolean;
  is_upcoming: boolean;
  days_until_start: number | null;
  days_until_end: number | null;
}

export interface RoadOpening {
  event_id: string;
  start_date: string;
  end_date: string;
  svc_dept: string;
  road_name: string;
  other: string;
  is_active: boolean;
  is_upcoming: boolean;
  days_until_start: number | null;
  days_until_end: number | null;
}

export interface TaxiStand {
  taxi_code: string;
  latitude: number;
  longitude: number;
  bfa: string;
  ownership: string;
  type: string;
  name: string;
  is_bfa_accessible: boolean;
}

export interface RoadEvent {
  event_id: string;
  event_type: 'road_work' | 'road_opening';
  road_name: string;
  start_date: string;
  end_date: string;
  svc_dept: string;
  description: string;
  status: 'active' | 'upcoming' | 'completed';
}

export interface RoadsAnalytics {
  road_works: {
    total: number;
    active: number;
    upcoming: number;
    completed: number;
  };
  road_openings: {
    total: number;
    active: number;
    upcoming: number;
  };
  taxi_stands: {
    total: number;
    bfa_accessible: number;
    by_ownership: Record<string, number>;
  };
  timestamp: string;
}

export interface RoadSpeedContext {
  timestamp: string;
  roads: {
    road: string;
    avg_current_speed: number;
    avg_predicted_speed: number;
    avg_change: number;
    segment_count: number;
  }[];
  total_roads: number;
}

export interface MapFeature {
  type: 'Feature';
  geometry: {
    type: 'Point';
    coordinates: [number, number];
  };
  properties: {
    type: string;
    taxi_code: string;
    name: string;
    ownership: string;
    bfa_accessible: boolean;
  };
}

export interface RoadsMapData {
  type: 'FeatureCollection';
  features: MapFeature[];
  bbox: [number, number, number, number];
}

export async function fetchRoadWorks(limit = 100, offset = 0, status?: string, roadName?: string): Promise<{ total: number; limit: number; offset: number; works: RoadWork[] }> {
  const url = new URL(`${API_BASE}/api/mobility/roads/works`);
  url.searchParams.set('limit', limit.toString());
  url.searchParams.set('offset', offset.toString());
  if (status) url.searchParams.set('status', status);
  if (roadName) url.searchParams.set('road_name', roadName);
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch road works: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadOpenings(limit = 100, offset = 0, status?: string): Promise<{ total: number; limit: number; offset: number; openings: RoadOpening[] }> {
  const url = new URL(`${API_BASE}/api/mobility/roads/openings`);
  url.searchParams.set('limit', limit.toString());
  url.searchParams.set('offset', offset.toString());
  if (status) url.searchParams.set('status', status);
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch road openings: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTaxiStands(limit = 500, offset = 0, bfaOnly = false, ownership?: string): Promise<{ total: number; limit: number; offset: number; stands: TaxiStand[] }> {
  const url = new URL(`${API_BASE}/api/mobility/roads/taxi-stands`);
  url.searchParams.set('limit', limit.toString());
  url.searchParams.set('offset', offset.toString());
  if (bfaOnly) url.searchParams.set('bfa_only', 'true');
  if (ownership) url.searchParams.set('ownership', ownership);
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch taxi stands: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadEvents(limit = 100, offset = 0, eventType?: string, status?: string): Promise<{ total: number; limit: number; offset: number; events: RoadEvent[] }> {
  const url = new URL(`${API_BASE}/api/mobility/roads/events`);
  url.searchParams.set('limit', limit.toString());
  url.searchParams.set('offset', offset.toString());
  if (eventType) url.searchParams.set('event_type', eventType);
  if (status) url.searchParams.set('status', status);
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch road events: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadsAnalytics(): Promise<RoadsAnalytics> {
  const response = await fetch(`${API_BASE}/api/mobility/roads/analytics/summary`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch roads analytics: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadSpeedContext(): Promise<RoadSpeedContext> {
  const response = await fetch(`${API_BASE}/api/mobility/roads/speed-context`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch road speed context: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadsMapData(): Promise<RoadsMapData> {
  const response = await fetch(`${API_BASE}/api/mobility/roads/map-data`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch roads map data: ${response.statusText}`);
  }
  return response.json();
}

// Fire API
export interface FireIncident {
  id: string;
  title: string;
  source: string;
  source_url: string | null;
  reported_at: string | null; // ISO string
  location: string | null;
  incident_type: string | null;
  severity: 'CRITICAL' | 'HIGH' | 'MODERATE' | 'LOW' | 'UNKNOWN';
  status: 'ACTIVE' | 'RESOLVED' | 'UNKNOWN';
  affected_area: string | null;
  latitude: number | null;
  longitude: number | null;
  region: string | null;
  summary: string | null;
  data_quality_flags: string[];
}

export interface FireHistoryPoint {
  year: number;
  fires: number | null;
  source: string;
}

export interface FireReport {
  generated_at: string;
  domain: string;
  subdomain: string;
  active_incidents: FireIncident[];
  recent_incidents: FireIncident[];
  active_incident_count: number | null;
  critical_incident_count: number | null;
  incidents_today: number | null;
  resolved_recent_count: number | null;
  regional_counts: Record<string, number | null>;
  historical_fire_counts: FireHistoryPoint[];
  source_status: string;
  data_sources: string[];
  limitations: string[];
  warnings: string[];
  errors: string[];
  is_ml_prediction: boolean;
}

export async function fetchFireReport(): Promise<FireReport> {
  const response = await fetch(`${API_BASE}/api/fire/report`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch fire report: ${response.statusText}`);
  }
  return response.json();
}

// Traffic ML Prediction
export interface TrafficLinkPrediction {
  link_id: string;
  road_name: string;
  road_category: string;
  zone_id: string | null;
  zone_name: string | null;
  current_speed: number;
  predicted_speed: number;
  speed_change: number;
}

export interface TrafficDivisionForecast {
  division: string;
  current_avg_speed: number | null;
  predicted_avg_speed: number | null;
  speed_change: number | null;
  speed_change_percent: number | null;
  congestion_level: string;
  segment_count: number;
}

export interface TrafficPredictionResponse {
  prediction_timestamp: string;
  target_timestamp: string;
  prediction_horizon_minutes: number;
  model: string;
  is_ml_model: boolean;
  source: string;
  diagnostics: Record<string, any>;
  link_predictions: TrafficLinkPrediction[];
  divisions: TrafficDivisionForecast[];
}

export async function fetchTrafficPrediction(): Promise<TrafficPredictionResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120_000); // 120 seconds
  try {
    const response = await fetch(`${API_BASE}/api/mobility/traffic/predict`, {
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) {
      // Try to extract backend detail for a clearer error message
      let detail = response.statusText;
      try {
        const errJson = await response.json();
        if (errJson?.detail?.message) detail = errJson.detail.message;
        else if (errJson?.detail?.error) detail = errJson.detail.error;
        else if (errJson?.message) detail = errJson.message;
      } catch {}
      throw new Error(`Failed to fetch traffic prediction: ${detail}`);
    }
    return response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Traffic forecast request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}
