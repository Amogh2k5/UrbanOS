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
  const response = await fetch(`${API_BASE}/api/traffic/report`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch traffic report: ${response.statusText}`);
  }
  return response.json();
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
  const url = new URL(`${API_BASE}/api/pollution/predict`);
  if (t0) {
    url.searchParams.set('t0', t0);
  }
  const response = await fetch(url.toString(), { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to fetch PM2.5 prediction: ${response.statusText}`);
  }
  return response.json();
}
