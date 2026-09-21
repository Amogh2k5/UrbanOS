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
