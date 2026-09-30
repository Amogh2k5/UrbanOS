/* eslint-disable @typescript-eslint/no-explicit-any */
export interface DomainStatus {
  domain: string;
  available: boolean;
  overall_status?: string;
  overall_risk?: string;
  risk_level?: string;
  key_metrics: Record<string, any>;
  active_alert_count?: number;
  affected_zones: string[];
  primary_risk_factors: string[];
  confidence?: string;
  limitations: string[];
  is_ml_prediction?: boolean;
  generated_at?: string;
  error?: string;
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
  cascading_risk?: string;
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
  evidence: any[];
  confidence: "high" | "medium" | "low";
  limitations: string[];
  source_reports: Record<string, any>;
  is_ml_prediction: boolean;
}
