/* eslint-disable @typescript-eslint/no-explicit-any */
import { CitySituationReport } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
      throw new Error('Traffic forecast request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function fetchTrafficPrediction(): Promise<any> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120_000); // 120 seconds
  try {
    const response = await fetch(`${API_BASE}/api/traffic/predict`, {
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
      throw new Error(`Failed to fetch traffic prediction: ${detail}`);
    }
    return response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Traffic prediction request timed out');
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

export async function fetchPm25Prediction(t0?: string): Promise<any> {
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

export async function fetchTransitStatus(limitAlerts = 20): Promise<any> {
  const response = await fetch(`${API_BASE}/api/mobility/transit/status?limit_alerts=${limitAlerts}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch transit status: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchBusServices(limit = 1000, serviceNo?: string, operator?: string): Promise<any[]> {
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

export async function fetchBusRoutes(serviceNo: string, operator: string, direction: number): Promise<any[]> {
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
}): Promise<any[]> {
  const url = new URL(`${API_BASE}/api/mobility/transit/bus-stops`);
  if (options?.busStopCode) {
    url.searchParams.set('bus_stopCode', options.busStopCode);
  } else if (options?.allStops) {
    url.searchParams.set('all_stops', 'true');
    if (options.limit) url.searchParams.set('limit', options.limit.toString());
  } else if (options?.lat !== undefined && options?.lon !== undefined) {
    url.searchParams.set('lat', options.lat.toString());
    url.searchParams.set('lon', options.lon.toString());
    url.searchParams.set('radius_km', (options.radiusKm || 1).toString());
    url.searchParams.set('limit', (options.limit || 200).toString());
  } else {
    throw new Error('Provide either bus_stopCode, all_stops=true, or lat/lon');
  }
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch bus stops: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTrainAlerts(line?: string, limit = 20): Promise<any[]> {
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
    completed: number;
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

export async function fetchRoadWorks(limit = 100, offset = 0, status?: string, roadName?: string): Promise<any> {
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

export async function fetchRoadOpenings(limit = 100, offset = 0, status?: string): Promise<any> {
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

export async function fetchTaxiStands(limit = 500, offset = 0, bfaOnly = false, ownership?: string): Promise<any> {
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

export async function fetchRoadEvents(limit = 100, offset = 0, eventType?: string, status?: string): Promise<any> {
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

export async function fetchRoadsAnalytics(): Promise<any> {
  const response = await fetch(`${API_BASE}/api/mobility/roads/analytics/summary`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch roads analytics: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadSpeedContext(): Promise<any> {
  const response = await fetch(`${API_BASE}/api/mobility/roads/speed-context`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch road speed context: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchRoadsMapData(): Promise<any> {
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

export async function fetchFireReport(): Promise<any> {
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

// Types for overview
export interface ModuleKPI {
  label: string;
  value: any;
  unit: string;
}

export interface ModuleSummary {
  id: string;
  name: string;
  status: 'normal' | 'elevated' | 'critical' | 'unavailable';
  kpi: ModuleKPI | null;
  updated_at: string | null;
  detail_route: string;
}

export interface AlertItem {
  id?: string;
  domain: string;
  severity: string;
  title: string;
  description: string;
  timestamp: string;
  affected_zones: string[];
}

export interface OverviewCityResponse {
  generated_at: string;
  modules: ModuleSummary[];
  alerts: AlertItem[];
  ai_brief: string | null;
}

export interface ModuleDetailResponse {
  module_id: string;
  module_name: string;
  status: string;
  kpi: ModuleKPI | null;
  updated_at: string | null;
  summary: string;
  alerts: AlertItem[];
  cross_domain: string[];
  detail_route: string;
}

export interface ChatRequest {
  message: string;
  module_id?: string;
}

export interface ChatResponse {
  response: string;
}

// Overview API functions
export async function fetchOverviewCity(): Promise<any> {
  const response = await fetch(`${API_BASE}/api/overview/city`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch overview city: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchOverviewModule(moduleId: string): Promise<any> {
  const response = await fetch(`${API_BASE}/api/overview/module/${moduleId}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch overview module ${moduleId}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchChat(message: string, moduleId?: string): Promise<any> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000); // 30 seconds
  const url = new URL(`${API_BASE}/api/overview/chat`);
  try {
    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, module_id: moduleId }),
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try { const errJson = await response.json(); if (errJson?.detail) detail = errJson.detail; } catch {}
      throw new Error(`Failed to fetch chat response: ${detail}`);
    }
    return response.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Chat request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Water (Infrastructure) domain — mirrors backend/app/infrastructure/water/models.py
// ---------------------------------------------------------------------------
export type WaterDataKind = 'live' | 'latest_available' | 'historical' | 'forecast' | 'unavailable';
export type DrainCondition = 'NORMAL' | 'ELEVATED' | 'HIGH' | 'CRITICAL' | 'UNAVAILABLE';

export interface WaterSource {
  key: string;
  organization: string;
  name: string;
  identifier: string;
  url: string;
  purpose: string;
  update_frequency: string;
  coverage: string;
  authentication: string;
  data_kind: WaterDataKind;
  component: string;
  status: 'ok' | 'stale_cache' | 'unavailable';
  last_fetched_at?: string | null;
  latest_data_period?: string | null;
  record_count?: number | null;
  error?: string | null;
}

export interface WaterIndicator {
  key: string;
  label: string;
  value?: number | null;
  unit: string;
  period?: string | null;
  previous_value?: number | null;
  previous_period?: string | null;
  change_abs?: number | null;
  change_pct?: number | null;
  data_kind: WaterDataKind;
  source_key?: string | null;
}

export interface WaterSeries {
  key: string;
  label: string;
  unit: string;
  points: { year: number; value?: number | null }[];
  data_kind: WaterDataKind;
  source_key?: string | null;
}

export interface WaterDrainSensorStatus {
  sensor: { id: string; name?: string | null; latitude: number; longitude: number };
  condition: DrainCondition;
  water_level_m?: number | null;
  reference_depth_m?: number | null;
  percentage?: number | null;
  observed_at?: string | null;
  trend: 'rising' | 'falling' | 'stable' | 'unknown';
}

export interface WaterQualityParameter {
  key: string;
  parameter: string;
  unit: string;
  average?: string | null;
  range?: string | null;
  regulatory_limit?: string | null;
  compliance: 'WITHIN_LIMIT' | 'EXCEEDS_LIMIT' | 'NO_LIMIT_PUBLISHED' | 'UNKNOWN';
}

export interface WaterReport {
  generated_at: string;
  domain: string;
  subdomain: string;
  overall_status: 'NORMAL' | 'ELEVATED' | 'CRITICAL' | 'UNKNOWN';
  overall_risk: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';
  supply: {
    data_kind: WaterDataKind;
    status: 'SALES_DATA_ONLY' | 'UNAVAILABLE';
    period?: string | null;
    reservoir_storage_available: boolean;
    reservoir_storage_note: string;
    indicators: WaterIndicator[];
    newater_share_of_water_sales_pct?: number | null;
    series: WaterSeries[];
    limitations: string[];
  };
  drain: {
    data_kind: WaterDataKind;
    readings_available: boolean;
    sensor_locations_available: boolean;
    sensor_count: number;
    sensors_with_readings: number;
    condition_counts: Record<string, number>;
    thresholds: Record<string, string>;
    threshold_source: string;
    sensors: WaterDrainSensorStatus[];
    latest_reading_at?: string | null;
    invalid_sensor_records: number;
    limitations: string[];
  };
  usage: {
    data_kind: WaterDataKind;
    resolution: string;
    latest_year?: number | null;
    potable_total?: WaterIndicator | null;
    domestic?: WaterIndicator | null;
    non_domestic?: WaterIndicator | null;
    domestic_share_pct?: number | null;
    non_domestic_share_pct?: number | null;
    cagr_pct_since_2015?: number | null;
    series: WaterSeries[];
    consistency_warnings: string[];
    limitations: string[];
  };
  forecast: {
    available: boolean;
    data_kind: WaterDataKind;
    reason: string;
    target: string;
    observations: number;
    frequency: string;
    minimum_observations_required: number;
    mae?: number | null;
    rmse?: number | null;
  };
  newater: {
    data_kind: WaterDataKind;
    latest?: WaterIndicator | null;
    share_of_water_sales_pct?: number | null;
    cagr_pct_since_2015?: number | null;
    series: WaterSeries[];
    long_run_source_note: string;
    limitations: string[];
  };
  quality: {
    data_kind: WaterDataKind;
    reporting_period?: string | null;
    frequency: string;
    parameters: WaterQualityParameter[];
    other_parameter_count: number;
    limit_source: string;
    limitations: string[];
  };
  alerts: { id: string; severity: 'LOW' | 'MODERATE' | 'HIGH'; category: string; message: string; evidence: string[]; data_kind: WaterDataKind }[];
  insights: { question: string; answer: string; data_kind: WaterDataKind }[];
  sources: WaterSource[];
  data_timestamps: Record<string, unknown>;
  confidence: 'high' | 'medium' | 'low';
  limitations: string[];
  warnings: string[];
  errors: string[];
  is_ml_prediction: boolean;
}

export async function fetchWaterReport(refresh = false): Promise<WaterReport> {
  const response = await fetch(`${API_BASE}/api/water/report${refresh ? '?refresh=true' : ''}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch water report: ${response.statusText}`);
  }
  return response.json();
}