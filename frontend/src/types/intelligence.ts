/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * One evidence-backed statement produced by a deterministic domain rule.
 * Mirrors `backend.app.intelligence.contracts.Finding`.
 */
export interface EvidenceRef {
  source_key?: string | null;
  source_name?: string | null;
  metric: string;
  value?: any;
  unit?: string;
  observed_at?: string | null;
  data_kind?: DataKind;
}

export type DataKind =
  | "live"
  | "latest_available"
  | "historical"
  | "forecast"
  | "unavailable";

export interface Finding {
  id: string;
  domain: string;
  title: string;
  answer: string;
  data_kind: DataKind;
  category: string;
  question?: string | null;
  severity?: "LOW" | "MODERATE" | "HIGH" | null;
  evidence: string[];
  evidence_refs: EvidenceRef[];
  sources: string[];
  observed_at?: string | null;
  freshness?: "live" | "recent" | "stale" | "unknown";
  affected_area?: string | null;
  limitations: string[];
  metrics: Record<string, any>;
}

export interface DomainStatus {
  domain: string;
  available: boolean;
  overall_status?: string | null;
  overall_risk?: string | null;
  risk_level?: string | null;
  key_metrics: Record<string, any>;
  active_alert_count?: number | null;
  affected_zones: string[];
  primary_risk_factors: string[];
  confidence?: string | null;
  limitations: string[];
  is_ml_prediction?: boolean;
  generated_at?: string | null;
  source_status?: string | null;
  warnings?: string[];
  errors?: string[];
  error?: string | null;
  findings?: Finding[];
  detail_route?: string | null;
  display_name?: string | null;
}

export interface CrossDomainImpact {
  type: string;
  description: string;
  severity: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  affected_zones: string[];
  domains_involved: string[];
  evidence: string[];
}

export interface PriorityIncident {
  id: string;
  type: string;
  domain: string;
  severity: "LOW" | "MODERATE" | "HIGH";
  description: string;
  affected_zones: string[];
  source_report: string;
  related_domains: string[];
  cascading_risk?: string | null;
}

export interface CityEvidenceEntry {
  source: string;
  subdomain?: string;
  generated_at?: string | null;
  confidence?: string | null;
  key_metrics?: Record<string, any>;
  limitations?: string[];
}

export interface CitySituationReport {
  generated_at: string;
  overall_city_status: "NORMAL" | "ELEVATED" | "DISRUPTED" | "CRITICAL" | "UNKNOWN";
  overall_risk_level: "LOW" | "MODERATE" | "HIGH" | "CRITICAL" | "UNKNOWN";
  domain_status: Record<string, DomainStatus>;
  priority_incidents: PriorityIncident[];
  cross_domain_impacts: CrossDomainImpact[];
  city_level_recommendations: string[];
  affected_zones: string[];
  evidence: CityEvidenceEntry[];
  confidence: "high" | "medium" | "low";
  limitations: string[];
  data_gaps?: string[];
  warnings?: string[];
  errors?: string[];
  source_reports: Record<string, any>;
  is_ml_prediction: boolean;
}
